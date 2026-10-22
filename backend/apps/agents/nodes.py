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
from apps.agents.anchoring import anchor_with_drops, new_file_lines
from apps.agents.budget import estimate_tokens
from apps.agents.diffs import hunk_ranges, reconstruct_new_file
from apps.agents.providers import ProviderError
from apps.agents.schema import (
    GROUNDING_SCHEMA,
    INTENT_SCHEMA,
    RESPONSE_SCHEMA,
    SchemaError,
    parse_findings,
)
from apps.agents.static_analysis import is_syntax_code, run_analysis
from apps.agents.types import AgentRun, Category, Finding, Placement, ReviewConfig, Severity

logger = logging.getLogger(__name__)

# Priority order when the budget is tight. Security first because a missed
# vulnerability is the costliest omission; test coverage last because its absence
# is the least likely to matter in a single PR.
AGENT_PRIORITY = ("security", "grounding", "diff_intent", "test_coverage")


def _call_model(
    runtime, agent, model, system_prompt, user_message, estimated, schema=RESPONSE_SCHEMA
):
    """One budgeted model call, returning (findings_raw, AgentRun).

    Shared by every LLM-backed node so budgeting, telemetry and error handling are
    identical across agents rather than reimplemented four times.

    The run is stamped with the model that SERVED the call, not the one requested:
    after a failover those differ, and cost, telemetry and the comment must describe
    what actually ran.
    """
    run = AgentRun(name=agent, model=model, requested_model=model)

    if not runtime.budget.reserve(agent, estimated):
        run.skipped_reason = runtime.budget.skipped[-1][1]
        return None, run

    started = time.perf_counter()
    try:
        response, provider_name, used_fallback = runtime.complete(
            model, system_prompt, user_message, schema=schema
        )
    except ProviderError as exc:
        run.latency_ms = int((time.perf_counter() - started) * 1000)
        # Nothing served the call, so no model is named as having run it.
        run.model = ""
        run.error = str(exc)[:400]
        return None, run

    run.latency_ms = int((time.perf_counter() - started) * 1000)
    run.provider = provider_name
    run.model = getattr(response, "model", "") or model
    run.used_fallback = used_fallback
    run.provider_model = getattr(response, "provider_model", "")
    run.system_fingerprint = getattr(response, "system_fingerprint", "")
    run.rate_limits = dict(getattr(response, "rate_limits", {}) or {})
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
            evidence=f.evidence,
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
        schema=INTENT_SCHEMA,
    )

    intent = ""
    if raw is not None:
        intent = prompts.extract_intent(raw)
        run.succeeded = bool(intent)
        if not intent:
            # A model answered but said nothing usable. Recorded as an error so the
            # run can never be mistaken for one that worked and found nothing.
            run.error = "schema: no intent in the model's response"

    return {"intent": intent, "runs": [run]}


# --------------------------------------------------------------- static analysis


def static_analysis(state):
    """Real linters, no model. Free in both tokens and latency."""
    prepared = state["prepared"]
    # No model: the tools that ran are reported in `detail`, never in `model`, so
    # nothing downstream mistakes a linter for an LLM or prices it as one.
    run = AgentRun(name="static_analysis")

    started = time.perf_counter()
    runtime = state.get("runtime")
    contents, complete, partial = _sources(
        getattr(runtime, "fetch_source", None),
        runtime.config.max_source_bytes if runtime else ReviewConfig().max_source_bytes,
        prepared,
    )

    try:
        report = run_analysis(contents, complete=complete)
    except Exception as exc:  # noqa: BLE001 - a linter must not fail the review
        run.latency_ms = int((time.perf_counter() - started) * 1000)
        run.error = f"{type(exc).__name__}: {exc}"[:400]
        logger.exception("Static analysis failed")
        return {"findings": [], "runs": [run]}

    run.latency_ms = int((time.perf_counter() - started) * 1000)
    run.detail = report.describe()
    if partial and report.looked:
        run.detail += f" · {len(partial)} file(s) from diff hunks only"

    # Only claim success if a tool actually looked. Nothing having run is a skip
    # with the reason named, so "0 findings" never stands in for "never checked".
    if not report.looked:
        run.skipped_reason = run.detail or "no Python or JS/TS files to analyse"
        return {"findings": [], "runs": [run]}

    run.succeeded = True

    added = {entry.path: entry.added_lines for entry in prepared.files}
    new_files = {entry.path for entry in prepared.files if entry.is_new_file}
    texts = {
        entry.path: {n: line.text for n, line in new_file_lines(entry).items()}
        for entry in prepared.files
    }
    findings = []
    for item in report.findings:
        # Only lines the PR added. A linter over whole files otherwise flags
        # pre-existing code the author did not write - context lines included. Never
        # moved to a nearby added line either: a tool names the exact line it means.
        if item.line not in added.get(item.file, ()):
            continue
        findings.append(
            Finding(
                file=item.file,
                line=item.line,
                severity=Severity.BLOCKING if item.severity == "blocking" else Severity.NIT,
                category=_tool_category(item),
                # The tool and rule lead, so the finding names its rule wherever
                # it is shown: "ruff F401: `os` imported but unused".
                message=_tool_message(item, contents, new_files),
                agent="static_analysis",
                rule=f"{item.tool} {item.code}".strip(),
                evidence=texts.get(item.file, {}).get(item.line, ""),
                placement=Placement.INLINE,
                anchored_by="tool",
            )
        )

    run.findings_count = len(findings)
    return {"findings": findings, "runs": [run]}


def _tool_message(item, contents, new_files):
    message = f"{item.tool} {item.code}: {item.message}".strip()
    if item.tool == "ruff" and is_syntax_code(item.code) and item.file in new_files:
        indent = uniform_indent(contents.get(item.file, ""))
        if indent:
            message += f" (the whole file is indented by {indent})"
    return message


def _sources(fetch_source, limit, prepared):
    """What to lint for each file: `(contents, complete_paths, partial_paths)`.

    An added file's hunks are the whole file. A modified file's hunks are not, so its
    full content at the PR head is fetched when the caller supplied a way to; a
    reconstruction from hunks is the fallback, and the linter is told it is partial.
    """
    contents, complete, partial = {}, set(), set()

    for entry in prepared.files:
        if entry.is_new_file:
            contents[entry.path] = reconstruct_new_file(entry.text)
            complete.add(entry.path)
            continue

        source = None
        if fetch_source is not None:
            try:
                source = fetch_source(entry.path)
            except Exception:  # noqa: BLE001 - a failed fetch costs precision, not the review
                logger.exception("Could not fetch %s for static analysis", entry.path)
            if source is not None and len(source.encode("utf-8")) > limit:
                source = None

        if source is not None:
            contents[entry.path] = source
            complete.add(entry.path)
        else:
            contents[entry.path] = reconstruct_new_file(entry.text)
            partial.add(entry.path)

    return contents, complete, partial


def _tool_category(item):
    if item.tool == "bandit" or item.code.startswith(
        ("S", "js-eval", "js-new-function", "js-inner", "js-dangerously")
    ):
        return Category.SECURITY
    return Category.CORRECTNESS


def uniform_indent(content):
    """ "3 spaces" when every non-blank line starts with the same indent, else "".

    Testbed PR #8's first commit indented all of money.py by three spaces: ruff says
    "Unexpected indentation" at 1:1, which reads like one stray line rather than a
    whole file pasted in at the wrong depth.
    """
    lines = [line for line in content.splitlines() if line.strip()]
    if not lines:
        return ""
    prefixes = {line[: len(line) - len(line.lstrip())] for line in lines}
    if len(prefixes) != 1:
        # Nested code indents further; what matters is the shallowest line.
        shallowest = min(prefixes, key=len)
        if not shallowest or not all(p.startswith(shallowest) for p in prefixes):
            return ""
        prefix = shallowest
    else:
        (prefix,) = prefixes
    if not prefix or len(set(prefix)) != 1:
        return ""
    unit = "space" if prefix[0] == " " else "tab"
    return f"{len(prefix)} {unit}{'s' if len(prefix) != 1 else ''}"


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
    anchored, dropped = anchor_with_drops(findings, prepared)
    return {"findings": anchored, "runs": [run], "dropped": dropped}


# ----------------------------------------------------------------------- grounding


def grounding(state):
    """The RAG agent: does this change duplicate or contradict existing code?

    Every finding must cite a chunk that was actually retrieved (spec section 6);
    uncited ones are dropped rather than trusted.
    """
    runtime = state["runtime"]
    prepared = state["prepared"]
    run = AgentRun(name="grounding", requested_model=runtime.config.cheap_model)

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

    found_any = bool(retrieved)
    retrieved = exclude_own_changes(retrieved, prepared)
    if not retrieved:
        run.skipped_reason = (
            "only this pull request's own changes were retrieved"
            if found_any
            else "nothing retrieved; repository may not be indexed"
        )
        return {"findings": [], "runs": [run]}

    message = prompts.build_grounding_message(prepared, retrieved, state.get("intent", ""))
    raw, call_run = _call_model(
        runtime,
        "grounding",
        runtime.config.cheap_model,
        prompts.GROUNDING_SYSTEM_PROMPT,
        message,
        estimate_tokens(message) + 500,
        schema=GROUNDING_SCHEMA,
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
            cited=citation,
            evidence=f.evidence,
        )
        for f, citation in kept
    ]
    findings, off_diff = anchor_with_drops(findings, prepared)
    call_run.findings_count = len(findings)
    uncited = [(f, "uncited: citation is not inside a retrieved excerpt") for f in dropped]

    return {
        "findings": findings,
        "runs": [call_run],
        "retrieved": retrieved,
        "dropped": uncited + off_diff,
    }


def exclude_own_changes(retrieved, prepared):
    """Drop retrieved chunks that are this PR's own change, not existing code.

    The index holds the base branch, so a file the PR modifies is retrieved as well -
    and on testbed PR #5 grounding cited the PR's own `app/reports.py:5-13` as
    "logic that already exists". A chunk is excluded when it is in a changed file and
    overlaps a hunk, on either side: index line numbers are the base's (old side),
    and a re-indexed branch could match the new side.
    """
    spans = {entry.path: hunk_ranges(entry.text) for entry in prepared.files}

    def overlaps(chunk):
        for old_start, old_end, new_start, new_end in spans.get(chunk.file_path, ()):
            for start, end in ((old_start, old_end), (new_start, new_end)):
                if chunk.line_start <= end and chunk.line_end >= start:
                    return True
        return False

    return [chunk for chunk in retrieved if not overlaps(chunk)]


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
    anchored, dropped = anchor_with_drops(findings, prepared)
    return {"findings": anchored, "runs": [run], "dropped": dropped}
