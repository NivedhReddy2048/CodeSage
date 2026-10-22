"""The Phase 8 baseline: one LLM prompt instead of the multi-agent pipeline.

Spec section 16 compares CodeSage with "a single LLM prompt with the raw diff, no RAG
and no agents". To isolate the architecture rather than post-processing added
later, the baseline gets exactly what every pipeline agent gets around its model
call - the numbered diff, the evidence contract, anchoring, the severity policy and
synthesis - and nothing the pipeline adds on top: no intent, security, test-coverage
or grounding agents, no retrieval, no static analysis.

It calls the pipeline's PRIMARY model (gpt-oss-120b); most pipeline agents use the
cheaper gpt-oss-20b, so the baseline is not handicapped on model size.
"""

import time

from apps.agents import agent_prompts, nodes, policy
from apps.agents.anchoring import anchor_with_drops
from apps.agents.budget import estimate_tokens
from apps.agents.diffs import prepare
from apps.agents.graph import Runtime, _as_call
from apps.agents.synthesis import synthesise_traced
from apps.agents.types import ReviewConfig, ReviewResult, TraceEntry

AGENT = "baseline"


def run_baseline(diff, context, config=None):
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

    runtime = Runtime(config)
    message = agent_prompts.build_baseline_message(prepared, context)
    raw, run = nodes._call_model(
        runtime,
        AGENT,
        config.primary_model,
        agent_prompts.BASELINE_SYSTEM_PROMPT,
        message,
        estimate_tokens(message) + 800,
    )
    findings = nodes._parse(raw, run, config.max_findings, AGENT) if raw is not None else []

    anchored, off_diff = anchor_with_drops(findings, prepared)
    kept, out_of_scope = policy.apply(anchored)
    result.findings, trace = synthesise_traced(kept, config.max_findings)
    result.trace = trace + [
        TraceEntry(finding, "dropped", reason) for finding, reason in off_diff + out_of_scope
    ]
    result.dropped = off_diff + out_of_scope
    result.agent_runs = [run]
    result.calls = [_as_call(run)] if (run.requested_model or run.provider) else []
    result.model_used = run.model
    result.succeeded = run.succeeded
    if not run.succeeded:
        result.failure_reason = run.error or run.skipped_reason or "the model did not answer"
    result.duration_ms = int((time.perf_counter() - started) * 1000)
    return result
