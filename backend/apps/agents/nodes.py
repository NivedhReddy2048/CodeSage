"""The six agents from spec section 5, as plain functions.

Each node takes the graph state and returns a partial update. None of them import
Django; retrieval arrives as a callable the caller supplies, so the package stays
free of the ORM.

Model tiering is driven by the shared 8000 TPM ceiling: the cheap agents run on
`gpt-oss-20b`, Security gets `gpt-oss-120b`, and Static analysis uses no model at
all because it runs real tools.
"""

import logging
import time

from apps.agents import agent_prompts as prompts
from apps.agents import citations
from apps.agents.budget import estimate_tokens
from apps.agents.providers import ProviderError
from apps.agents.schema import SchemaError, parse_findings
from apps.agents.static_analysis import analyse
from apps.agents.types import AgentRun, Category, Finding, Severity

logger = logging.getLogger(__name__)

# Priority order when the budget is tight. Security first because a missed
# vulnerability is the costliest omission; test coverage last because its absence
# is the least likely to matter in a single PR.
AGENT_PRIORITY = ("security", "grounding", "diff_intent", "test_coverage")


def _call_model(runtime, agent, model, system_prompt, user_message, estimated):
    """One budgeted model call, returning (findings_raw, AgentRun).

    Shared by every LLM-backed node so budgeting, telemetry and error handling are
    identical across agents rather than reimplemented four times.
    """
    run = AgentRun(name=agent, model=model)

    if not runtime.budget.reserve(agent, estimated):
        run.skipped_reason = runtime.budget.skipped[-1][1]
        return None, run

    started = time.perf_counter()
    try:
        response, provider_name, used_fallback = runtime.complete(
            model, system_prompt, user_message
        )
    except ProviderError as exc:
        run.latency_ms = int((time.perf_counter() - started) * 1000)
        run.error = str(exc)[:400]
        return None, run

    run.latency_ms = int((time.perf_counter() - started) * 1000)
    run.provider = provider_name
    run.used_fallback = used_fallback
    run.input_tokens = response.input_tokens
    run.output_tokens = response.output_tokens
    run.succeeded = True

    runtime.budget.record_actual(estimated, response.input_tokens + response.output_tokens)
    return response.content, run


def _parse(raw, run, max_findings, agent):
    """Parse a model response into findings, recording a schema failure on the run."""
    try:
        findings = parse_findings(raw, max_findings)
    except SchemaError as exc:
        run.error = f"schema: {exc}"[:400]
        run.succeeded = False
        return []

    tagged = [
        Finding(
            file=f.file,
            line=f.line,
            severity=f.severity,
            category=f.category,
            message=f.message,
            agent=agent,
        )
        for f in findings
    ]
    run.findings_count = len(tagged)
    return tagged


# ------------------------------------------------------------------ diff / intent


def diff_intent(state):
    """Classify what the change is doing, to focus the other agents.

    Cheap model: this produces a sentence and a label, not analysis.
    """
    runtime = state["runtime"]
    prepared = state["prepared"]

    message = prompts.build_intent_message(prepared, state["context"])
    raw, run = _call_model(
        runtime,
        "diff_intent",
        runtime.config.cheap_model,
        prompts.INTENT_SYSTEM_PROMPT,
        message,
        estimate_tokens(message) + 200,
    )

    intent = ""
    if raw:
        intent = prompts.extract_intent(raw)
        run.succeeded = bool(intent)

    return {"intent": intent, "runs": [run]}


# --------------------------------------------------------------- static analysis


def static_analysis(state):
    """Real linters, no model. Free in both tokens and latency."""
    prepared = state["prepared"]
    run = AgentRun(name="static_analysis", model="ruff+bandit+pattern-scan")

    started = time.perf_counter()
    contents = {entry.path: _new_file_text(entry) for entry in prepared.files}

    try:
        tool_findings = analyse(contents)
    except Exception as exc:  # noqa: BLE001 - a linter must not fail the review
        run.latency_ms = int((time.perf_counter() - started) * 1000)
        run.error = f"{type(exc).__name__}: {exc}"[:400]
        logger.exception("Static analysis failed")
        return {"findings": [], "runs": [run]}

    run.latency_ms = int((time.perf_counter() - started) * 1000)
    run.succeeded = True

    findings = []
    for item in tool_findings:
        # Only report on lines the PR actually touched: a linter run over whole
        # files will otherwise flag pre-existing issues the author did not write.
        if not prepared.allows(item.file, item.line):
            continue
        findings.append(
            Finding(
                file=item.file,
                line=item.line,
                severity=Severity.BLOCKING if item.severity == "blocking" else Severity.NIT,
                category=_tool_category(item),
                message=f"{item.message} ({item.tool} {item.code})".strip(),
                agent="static_analysis",
            )
        )

    run.findings_count = len(findings)
    return {"findings": findings, "runs": [run]}


def _tool_category(item):
    if item.tool == "bandit" or item.code.startswith(("S", "js-eval", "js-inner")):
        return Category.SECURITY
    return Category.CORRECTNESS


def _new_file_text(entry):
    """Reconstruct the post-change file content from its diff section.

    Only the added and context lines, which is what the new file looks like within
    the hunks. Enough for a linter to see the changed code in context; not a full
    file, which the diff does not contain.
    """
    lines = []
    for raw in entry.text.splitlines():
        if raw.startswith(("+++", "---", "@@", "diff --git", "index ", "\\")):
            continue
        if raw.startswith("+"):
            lines.append(raw[1:])
        elif raw.startswith("-"):
            continue
        else:
            lines.append(raw[1:] if raw.startswith(" ") else raw)
    return "\n".join(lines)


# ------------------------------------------------------------------------ security


def security(state):
    """Focused security pass on the biggest model available."""
    runtime = state["runtime"]
    prepared = state["prepared"]

    message = prompts.build_security_message(prepared, state["context"], state.get("intent", ""))
    raw, run = _call_model(
        runtime,
        "security",
        runtime.config.primary_model,
        prompts.SECURITY_SYSTEM_PROMPT,
        message,
        estimate_tokens(message) + 600,
    )
    if raw is None:
        return {"findings": [], "runs": [run]}

    findings = _parse(raw, run, runtime.config.max_findings, "security")
    return {"findings": _within_diff(findings, prepared), "runs": [run]}


# ----------------------------------------------------------------------- grounding


def grounding(state):
    """The RAG agent: does this change duplicate or contradict existing code?

    Every finding must cite a chunk that was actually retrieved (spec section 6);
    uncited ones are dropped rather than trusted.
    """
    runtime = state["runtime"]
    prepared = state["prepared"]
    run = AgentRun(name="grounding", model=runtime.config.cheap_model)

    if runtime.retrieve is None:
        run.skipped_reason = "no retrieval configured"
        return {"findings": [], "runs": [run]}

    query = prompts.build_retrieval_query(prepared, state.get("intent", ""))
    try:
        retrieved = runtime.retrieve(query)
    except Exception as exc:  # noqa: BLE001 - retrieval failure must not fail review
        run.error = f"retrieval failed: {exc}"[:400]
        logger.exception("Retrieval failed")
        return {"findings": [], "runs": [run]}

    if not retrieved:
        run.skipped_reason = "nothing retrieved; repository may not be indexed"
        return {"findings": [], "runs": [run]}

    message = prompts.build_grounding_message(prepared, retrieved, state.get("intent", ""))
    raw, call_run = _call_model(
        runtime,
        "grounding",
        runtime.config.cheap_model,
        prompts.GROUNDING_SYSTEM_PROMPT,
        message,
        estimate_tokens(message) + 500,
    )
    # Keep the retrieval context on the run that is reported.
    call_run.name = "grounding"
    if raw is None:
        return {"findings": [], "runs": [call_run], "retrieved": retrieved}

    parsed = _parse(raw, call_run, runtime.config.max_findings, "grounding")

    # Citation enforcement. The citation to check is `cited_file`/`cited_line` -
    # where the EXISTING code lives - not the finding's own location in the diff.
    # Checking the diff location instead silently dropped every grounded finding,
    # because the diff is never inside a retrieved chunk.
    cited = _cited_locations(raw)
    candidates = [(f, *cited.get((f.file, f.line), (f.file, f.line))) for f in parsed]
    kept, dropped = citations.validate(candidates, retrieved)
    if dropped:
        logger.info("Grounding dropped %s uncited findings", len(dropped))

    findings = [
        Finding(
            file=f.file,
            line=f.line,
            severity=f.severity,
            category=f.category,
            message=f"{f.message} (see {citation})",
            agent="grounding",
        )
        for f, citation in kept
    ]
    call_run.findings_count = len(findings)

    return {"findings": findings, "runs": [call_run], "retrieved": retrieved}


# ------------------------------------------------------------------ test coverage


def _cited_locations(raw):
    """Map each finding's diff location to the citation it supplied.

    Read from the raw payload because the shared schema parser drops the
    grounding-only `cited_file` / `cited_line` keys.
    """
    import json

    try:
        payload = json.loads((raw or "").strip().strip("`"))
    except json.JSONDecodeError:
        start, end = (raw or "").find("{"), (raw or "").rfind("}")
        if start == -1 or end <= start:
            return {}
        try:
            payload = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return {}

    mapping = {}
    for entry in (payload or {}).get("findings", []) or []:
        if not isinstance(entry, dict):
            continue
        try:
            key = (str(entry.get("file") or ""), int(entry.get("line")))
        except (TypeError, ValueError):
            continue
        cited_file = str(entry.get("cited_file") or "")
        try:
            cited_line = int(entry.get("cited_line"))
        except (TypeError, ValueError):
            cited_line = 0
        mapping[key] = (cited_file, cited_line)
    return mapping


def test_coverage(state):
    """Flag changed logic with no corresponding test change."""
    runtime = state["runtime"]
    prepared = state["prepared"]

    message = prompts.build_test_message(prepared, state.get("intent", ""))
    raw, run = _call_model(
        runtime,
        "test_coverage",
        runtime.config.cheap_model,
        prompts.TEST_SYSTEM_PROMPT,
        message,
        estimate_tokens(message) + 400,
    )
    if raw is None:
        return {"findings": [], "runs": [run]}

    findings = _parse(raw, run, runtime.config.max_findings, "test_coverage")
    return {"findings": _within_diff(findings, prepared), "runs": [run]}


def _within_diff(findings, prepared):
    """Drop findings pointing at lines the diff does not contain."""
    return [f for f in findings if prepared.allows(f.file, f.line)]
