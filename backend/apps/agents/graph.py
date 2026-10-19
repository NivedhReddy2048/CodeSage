"""The six-agent pipeline as a LangGraph graph (spec section 5).

    START -> diff_intent -> [ static_analysis, security, grounding, test_coverage ]
                                            |
                                            v
                                        synthesis -> END

`diff_intent` runs first because its classification is fed to the others. The four
analysis agents then fan out concurrently: three are independent LLM calls and one
is a local subprocess, so running them in sequence would make a review roughly as
slow as the sum of its parts for no benefit.

Verified against langgraph 1.2.16 rather than assumed, since the documentation moved
host: fan-out really is concurrent (three 0.4s nodes completed in 0.42s), and
`Annotated[list, operator.add]` reducers merge concurrent writes without loss, which
is what lets four agents append findings at once.
"""

import logging
import operator
import time
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from apps.agents import nodes
from apps.agents.budget import TokenBudget
from apps.agents.diffs import prepare
from apps.agents.providers import GeminiProvider, GroqProvider, ProviderError
from apps.agents.synthesis import synthesise
from apps.agents.types import ReviewConfig, ReviewResult

logger = logging.getLogger(__name__)


class GraphState(TypedDict, total=False):
    """Shared state.

    `findings` and `runs` carry `operator.add` reducers so the parallel agents can
    all append; without them concurrent writes to the same key would conflict.
    """

    runtime: object
    prepared: object
    context: object
    intent: str
    findings: Annotated[list, operator.add]
    runs: Annotated[list, operator.add]
    retrieved: list
    # Declared explicitly: LangGraph discards keys that are not part of the state
    # schema, and an undeclared `synthesised` silently produced empty reviews.
    synthesised: list


class Runtime:
    """Provider access, failover and budget for one review.

    Holds the per-review mutable state the nodes share, so a node never reaches for
    a global and two concurrent reviews cannot interfere.
    """

    def __init__(self, config, retrieve=None):
        self.config = config
        self.retrieve = retrieve
        self.budget = TokenBudget(config.token_budget)

    def complete(self, model, system_prompt, user_message, schema=None):
        """Call `model` on Groq, falling back to Gemini.

        Returns `(response, provider_name, used_fallback)`; `response.model` names the
        model that served it, which after a failover is not `model`. `schema` is the
        calling agent's output contract, enforced natively where the provider can.
        The breaker from phase 4
        still applies per provider, so an exhausted Groq quota is skipped rather
        than retried for every agent in the graph.
        """
        from apps.agents.breaker import get_breaker

        messages = [{"role": "user", "content": user_message}]
        errors = []

        attempts = []
        if self.config.groq_api_key:
            attempts.append(
                (
                    GroqProvider(
                        api_key=self.config.groq_api_key,
                        model=model,
                        timeout=self.config.request_timeout,
                        max_retries=self.config.max_retries,
                        backoff=self.config.backoff_seconds,
                    ),
                    False,
                )
            )
        if self.config.gemini_api_key:
            attempts.append(
                (
                    GeminiProvider(
                        api_key=self.config.gemini_api_key,
                        model=self.config.fallback_model,
                        timeout=self.config.request_timeout,
                        max_retries=self.config.max_retries,
                        backoff=self.config.backoff_seconds,
                    ),
                    bool(attempts),
                )
            )

        for provider, is_fallback in attempts:
            breaker = get_breaker(
                provider.name,
                self.config.breaker_failure_threshold,
                self.config.breaker_reset_seconds,
            )
            if not breaker.allows():
                errors.append(f"{provider.name}: circuit open")
                continue

            try:
                response = provider.complete(system_prompt, messages, schema=schema)
            except ProviderError as exc:
                breaker.record_failure()
                # The full provider error goes to the log and the stored run. The
                # public PR comment gets a short human reason instead.
                logger.warning("%s (%s) failed: %s", provider.name, provider.model, exc)
                errors.append(str(exc))
                continue

            breaker.record_success()
            if not response.model:
                response.model = provider.model
            return response, provider.name, is_fallback

        raise ProviderError("; ".join(errors) or "no provider configured")


def build_graph():
    """Wire and compile the graph. Compiled once per call; it is cheap and stateless."""
    graph = StateGraph(GraphState)

    graph.add_node("diff_intent", nodes.diff_intent)
    graph.add_node("static_analysis", nodes.static_analysis)
    graph.add_node("security", nodes.security)
    graph.add_node("grounding", nodes.grounding)
    graph.add_node("test_coverage", nodes.test_coverage)
    graph.add_node("synthesis", _synthesis_node)

    graph.add_edge(START, "diff_intent")

    # Fan out, then fan in. Several edges from one node make its targets run
    # concurrently; several edges into synthesis make it wait for all of them.
    parallel = ("static_analysis", "security", "grounding", "test_coverage")
    for name in parallel:
        graph.add_edge("diff_intent", name)
        graph.add_edge(name, "synthesis")

    graph.add_edge("synthesis", END)
    return graph.compile()


def _synthesis_node(state):
    """Merge, deduplicate and prioritise. No model call: this is pure logic.

    Spec section 5 describes synthesis as an agent, but everything it needs to do -
    dedupe, rank, decide blocking versus nit - is deterministic. Spending a model
    call on it would add latency, cost and a chance of hallucination to a step that
    has a correct answer.
    """
    merged = synthesise(state.get("findings", []))
    return {"findings": [], "runs": [], "synthesised": merged}


def run_pipeline(diff, context, config=None, retrieve=None):
    """Run the six-agent pipeline. The phase 5 entry point."""
    config = config or ReviewConfig()
    started = time.perf_counter()

    result = ReviewResult()
    prepared = prepare(diff, config.max_diff_bytes)
    result.skipped_files = list(prepared.skipped_files)
    result.truncated = prepared.truncated

    if not prepared.text.strip():
        result.succeeded = True
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    runtime = Runtime(config, retrieve=retrieve)

    try:
        final = build_graph().invoke(
            {
                "runtime": runtime,
                "prepared": prepared,
                "context": context,
                "intent": "",
                "findings": [],
                "runs": [],
                "retrieved": [],
            }
        )
    except Exception as exc:  # noqa: BLE001 - the graph must not raise past here
        logger.exception("Agent graph failed")
        result.succeeded = False
        result.failure_reason = f"{type(exc).__name__}: {exc}"[:500]
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result

    runs = final.get("runs", [])
    result.agent_runs = runs
    result.findings = final.get("synthesised", [])
    result.duration_ms = int((time.perf_counter() - started) * 1000)
    result.skipped_agents = list(runtime.budget.skipped)

    # Telemetry rolls up from the per-agent runs rather than being tracked twice.
    # Only model-backed agents become call rows: static analysis runs linters, and a
    # call row for it would be priced and counted as if it were an LLM.
    result.calls = [_as_call(run) for run in runs if run.requested_model or run.provider]

    succeeded = [r for r in runs if r.succeeded]
    llm_attempted = [r for r in runs if r.provider or (r.requested_model and r.error)]
    llm_succeeded = [r for r in succeeded if r.provider]

    # A review is only "successful" if at least one model actually answered. Static
    # analysis succeeding on its own is a degraded result, not a review, and 5c
    # turns that into an explicitly labelled degraded comment rather than letting a
    # thin lint pass masquerade as a full review.
    result.succeeded = bool(llm_succeeded) or (bool(succeeded) and not llm_attempted)
    if not result.succeeded:
        result.failure_reason = _summarise_failure(runs)
    elif llm_succeeded:
        result.model_used = ", ".join(sorted({r.model for r in llm_succeeded if r.model}))
        result.used_fallback = any(r.used_fallback for r in llm_succeeded)

    return result


def _as_call(run):
    from apps.agents.types import LLMCall

    return LLMCall(
        provider=run.provider or "none",
        # The serving model when a call succeeded at a provider; for an agent that
        # no provider served, the model it asked for, so the failed row says what
        # was attempted.
        model=run.model or run.requested_model,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        latency_ms=run.latency_ms,
        succeeded=run.succeeded,
        is_fallback=run.used_fallback,
        error=run.error or run.skipped_reason,
    )


def _summarise_failure(runs):
    errors = [r.error for r in runs if r.error]
    if errors:
        return errors[-1][:500]
    skips = [r.skipped_reason for r in runs if r.skipped_reason]
    if skips:
        return f"every agent was skipped: {skips[-1]}"
    return "no agent produced a result"
