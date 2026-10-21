"""The v1 review agent: one pass over the PR diff.

Phase 4 is deliberately a single agent. The LangGraph multi-agent pipeline and
retrieval grounding arrive in phase 5; proving the whole loop end to end first is
the point of this phase.

Public interface: `run_review(diff, context, config) -> ReviewResult`. Nothing in
this package imports Django.
"""

import logging
import time

from apps.agents import prompts
from apps.agents.anchoring import anchor_all
from apps.agents.breaker import get_breaker
from apps.agents.diffs import prepare
from apps.agents.providers import GeminiProvider, GroqProvider, ProviderError
from apps.agents.schema import SchemaError, parse_findings
from apps.agents.types import LLMCall, ReviewConfig, ReviewResult

logger = logging.getLogger(__name__)


def run_review(diff, context, config=None):
    """Review a unified diff and return structured findings."""
    config = config or ReviewConfig()
    started = time.perf_counter()

    result = ReviewResult()
    prepared = prepare(diff, config.max_diff_bytes)
    result.skipped_files = list(prepared.skipped_files)
    result.truncated = prepared.truncated

    if not prepared.text.strip():
        # Nothing reviewable is a successful review of nothing, not a failure. A
        # docs-only or lockfile-only PR lands here.
        result.succeeded = True
        result.duration_ms = _elapsed_ms(started)
        return result

    system_prompt = prompts.SYSTEM_PROMPT
    user_message = prompts.build_user_message(prepared, context)

    for provider, is_fallback in _provider_chain(config):
        breaker = get_breaker(
            provider.name, config.breaker_failure_threshold, config.breaker_reset_seconds
        )
        if not breaker.allows():
            result.calls.append(
                LLMCall(
                    provider=provider.name,
                    model=provider.model,
                    is_fallback=is_fallback,
                    error="circuit open; provider skipped",
                )
            )
            continue

        findings, calls, error = _attempt(
            provider, system_prompt, user_message, prepared, config, is_fallback
        )
        result.calls.extend(calls)

        if error is None:
            breaker.record_success()
            result.findings = findings
            result.succeeded = True
            result.model_used = provider.model
            result.used_fallback = is_fallback
            result.duration_ms = _elapsed_ms(started)
            return result

        # A schema failure is the model's fault, not the provider's: counting it
        # against the breaker would open the circuit on a healthy endpoint.
        if not isinstance(error, SchemaError):
            breaker.record_failure()
        logger.warning("Provider %s failed: %s", provider.name, error)

    result.succeeded = False
    result.failure_reason = _summarise_failure(result.calls)
    result.duration_ms = _elapsed_ms(started)
    return result


def _provider_chain(config):
    """Primary first, then fallback. Unconfigured providers are left out."""
    chain = []

    groq = GroqProvider(
        api_key=config.groq_api_key,
        model=config.primary_model,
        timeout=config.request_timeout,
        max_retries=config.max_retries,
        backoff=config.backoff_seconds,
    )
    if groq.configured:
        chain.append((groq, False))

    gemini = GeminiProvider(
        api_key=config.gemini_api_key,
        model=config.fallback_model,
        timeout=config.request_timeout,
        max_retries=config.max_retries,
        backoff=config.backoff_seconds,
    )
    if gemini.configured:
        chain.append((gemini, bool(chain)))

    return chain


def _attempt(provider, system_prompt, user_message, prepared, config, is_fallback):
    """One provider, with a single retry if the output fails the schema.

    Returns `(findings, calls, error)`; `error` is None on success.
    """
    calls = []
    messages = [{"role": "user", "content": user_message}]
    last_error = None

    # Two passes at most: the original, then one corrective retry. More than one
    # retry on a model that cannot follow the contract is just spent quota.
    for attempt in (1, 2):
        call = LLMCall(provider=provider.name, model=provider.model, is_fallback=is_fallback)
        started = time.perf_counter()

        try:
            response = provider.complete(system_prompt, messages)
        except ProviderError as exc:
            call.latency_ms = _elapsed_ms(started)
            call.error = str(exc)[:500]
            calls.append(call)
            return [], calls, exc

        call.latency_ms = _elapsed_ms(started)
        call.input_tokens = response.input_tokens
        call.output_tokens = response.output_tokens

        try:
            findings = parse_findings(response.content, config.max_findings)
        except SchemaError as exc:
            call.error = f"schema: {exc}"[:500]
            calls.append(call)
            last_error = exc
            if attempt == 1:
                messages = [
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": response.content[:2000]},
                    {"role": "user", "content": prompts.build_retry_message(exc)},
                ]
                continue
            return [], calls, exc

        call.succeeded = True
        calls.append(call)
        return _drop_unanchored(findings, prepared), calls, None

    return [], calls, last_error


def _drop_unanchored(findings, prepared):
    """Anchor each finding (see `anchoring`); drop those about files not in the diff.

    A model will confidently cite a plausible-looking line it never saw. Posting
    that as a review comment anchors it to unrelated code, which is worse than
    saying nothing: it looks authoritative and is wrong.
    """
    return anchor_all(findings, prepared)


def _summarise_failure(calls):
    errors = [call.error for call in calls if call.error]
    if not errors:
        return "No LLM provider is configured."
    return errors[-1][:500]


def _elapsed_ms(started):
    return int((time.perf_counter() - started) * 1000)
