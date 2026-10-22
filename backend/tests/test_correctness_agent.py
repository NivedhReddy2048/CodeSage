"""The correctness agent (issue #126).

DEV run 1: no agent owned correctness, so seven of the eight benchmark bugs the
pipeline missed were noticed only by test coverage ("no test covers the one-word
case") or by security, as speculation, and neither can block. The agent runs on the
primary model under the same evidence, anchoring and certainty rules as the others.
"""

import json
from pathlib import Path
from unittest import mock

from apps.agents import agent_prompts, policy
from apps.agents.budget import TokenBudget
from apps.agents.diffs import prepare
from apps.agents.graph import Runtime, run_pipeline
from apps.agents.nodes import correctness
from apps.agents.providers import ProviderResponse
from apps.agents.synthesis import synthesise_traced
from apps.agents.types import (
    Category,
    Finding,
    Placement,
    RepoContext,
    ReviewConfig,
    Severity,
)

CASE = Path(__file__).parents[2] / "eval" / "cases" / "dev" / "bugsinpy-thefuck-21"
DIFF = (CASE / "diff.patch").read_text(encoding="utf-8")
PATH = "thefuck/rules/git_fix_stash.py"
CONFIG = ReviewConfig(groq_api_key="k", gemini_api_key="", backoff_seconds=0, max_retries=1)

INDEX_ERROR = (
    "command.script.split()[1] raises IndexError when the command is a single word such "
    "as `git`; the old code checked the length first."
)
# What test coverage said about this line in DEV run 1.
UNTESTED = (
    "The new implementation assumes command.script has at least two words; if not, it "
    "will raise IndexError. No test covers the single-word script case."
)


def entry(line, message, evidence, severity="blocking", category="error-handling"):
    return {
        "file": PATH,
        "line": line,
        "severity": severity,
        "category": category,
        "message": message,
        "evidence": evidence,
    }


def run_node(findings, intent="", calls=None):
    def complete(self, model, system_prompt, user_message, schema=None):
        if calls is not None:
            calls.append((model, system_prompt, user_message))
        return ProviderResponse(json.dumps({"findings": findings}), 700, 300), "groq", False

    state = {
        "runtime": Runtime(CONFIG),
        "prepared": prepare(DIFF, 60_000),
        "context": RepoContext("nvbn/thefuck", 0, "Update " + PATH),
        "intent": intent,
    }
    with mock.patch.object(Runtime, "complete", complete):
        return correctness(state)


# ----------------------------------------------------------------------- the node


def test_one_call_to_the_primary_model_with_the_correctness_prompt():
    calls = []
    out = run_node([], intent="refactor: simplify match", calls=calls)

    ((model, system, message),) = calls
    assert model == CONFIG.primary_model
    assert system == agent_prompts.CORRECTNESS_SYSTEM_PROMPT
    assert "Change intent (from an earlier agent): refactor: simplify match" in message
    assert "    8 + |     return (command.script.split()[1] == 'stash'" in message
    (run,) = out["runs"]
    assert (run.name, run.succeeded, run.input_tokens) == ("correctness", True, 700)


def test_findings_are_tagged_and_anchored_by_their_evidence():
    out = run_node(
        [entry(6, INDEX_ERROR, "return (command.script.split()[1] == 'stash'")]  # model said :6
    )

    (finding,) = out["findings"]
    assert (finding.agent, finding.line, finding.anchored_by) == ("correctness", 8, "evidence")
    assert finding.placement == Placement.INLINE


def test_the_prompt_keeps_to_correctness():
    prompt = agent_prompts.CORRECTNESS_SYSTEM_PROMPT

    for owned in ("off-by-one", "missing, extra or misordered argument", "unhandled None"):
        assert owned in prompt
    assert "security defects or missing tests. Other agents cover them." in prompt
    assert '"may", "might" or' in prompt
    # The shared injection framing and output contract, like every agent.
    assert "UNTRUSTED DATA" in prompt
    assert prompt.rstrip().endswith("An empty findings list is a valid answer.")


# --------------------------------------------------------------------- the policy


def correctness_finding(message=INDEX_ERROR, category=Category.ERROR_HANDLING, **extra):
    fields = {
        "file": PATH,
        "line": 8,
        "severity": Severity.BLOCKING,
        "category": category,
        "message": message,
        "agent": "correctness",
        "evidence": "return (command.script.split()[1] == 'stash'",
        "placement": Placement.INLINE,
        "anchored_by": "evidence",
        **extra,
    }
    return Finding(**fields)


def test_a_definite_evidenced_defect_may_block():
    (kept,), dropped = policy.apply([correctness_finding()])

    assert (kept.severity, kept.downgraded, dropped) == (Severity.BLOCKING, "", [])


def test_speculation_or_no_evidence_is_a_nit():
    speculative = correctness_finding("This could raise IndexError for short commands.")
    snapped = correctness_finding(anchored_by="snap")

    kept, _ = policy.apply([speculative, snapped])

    assert [(f.severity, f.downgraded) for f in kept] == [
        (Severity.NIT, "speculative wording"),
        (Severity.NIT, "no evidence quoted from an added line"),
    ]


def test_security_tests_style_and_performance_are_out_of_its_scope():
    findings = [
        correctness_finding(category=category)
        for category in (
            Category.SECURITY,
            Category.TESTING,
            Category.STYLE,
            Category.PERFORMANCE,
        )
    ]
    claim = correctness_finding("Building the query this way allows SQL injection.")

    kept, dropped = policy.apply([*findings, claim])

    assert kept == []
    assert [reason for _, reason in dropped] == [
        "out of scope: correctness reporting security",
        "out of scope: correctness reporting testing",
        "out of scope: correctness reporting style",
        "out of scope: correctness reporting performance",
        "out of scope: correctness making a security claim",
    ]


def test_logic_categories_are_its_own():
    for category in (Category.CORRECTNESS, Category.CONCURRENCY, Category.RESOURCE_LEAK):
        assert policy.out_of_scope(correctness_finding(category=category)) == ""


# ------------------------------------------------------------------ synthesis


def untested(message=UNTESTED, line=8):
    return Finding(
        file=PATH,
        line=line,
        severity=Severity.NIT,
        category=Category.TESTING,
        message=message,
        agent="test_coverage",
        evidence="return (command.script.split()[1] == 'stash'",
        placement=Placement.INLINE,
        anchored_by="evidence",
    )


def test_the_defect_and_its_missing_test_merge_into_the_correctness_finding():
    kept, _ = policy.apply([untested(), correctness_finding()])

    final, trace = synthesise_traced(kept)

    (merged,) = final
    assert merged.agent == "correctness"
    assert merged.severity == Severity.BLOCKING
    assert merged.message == f"{INDEX_ERROR} (also noted by test coverage)"
    outcomes = {t.finding.agent: (t.outcome, t.reason) for t in trace}
    assert outcomes["correctness"] == ("kept", "")
    assert outcomes["test_coverage"] == (
        "merged",
        "merged into correctness's finding: same line, same issue",
    )


def test_correctness_leads_even_when_test_coverage_reads_more_certain():
    unsure = correctness_finding("The split may raise IndexError for a one-word command script.")
    kept, _ = policy.apply([untested(), unsure])

    (merged,) = synthesise_traced(kept)[0]

    assert merged.agent == "correctness"
    assert merged.message.endswith("(also noted by test coverage)")


def test_a_different_defect_or_line_is_not_merged():
    other = untested("No test covers the 'usage:' check against stderr.")
    elsewhere = untested(line=9)

    final, _ = synthesise_traced(policy.apply([other, elsewhere, correctness_finding()])[0])

    assert sorted(f.agent for f in final) == ["correctness", "test_coverage", "test_coverage"]
    assert not any("also noted" in f.message for f in final)


def test_other_agents_are_still_credited_as_flagging():
    lint = Finding(
        file=PATH,
        line=8,
        severity=Severity.NIT,
        category=Category.ERROR_HANDLING,
        message="pattern: IndexError on split()[1] when the command is a single word",
        agent="static_analysis",
        rule="ruff X1",
        placement=Placement.INLINE,
        anchored_by="tool",
    )
    kept, _ = policy.apply([untested(), lint, correctness_finding()])

    (merged,) = synthesise_traced(kept)[0]

    assert merged.message == (
        f"{INDEX_ERROR} (also flagged by static_analysis: ruff X1; also noted by test coverage)"
    )


# ------------------------------------------------------- budget and the pipeline


def test_each_model_has_its_own_budget():
    """Groq's per-minute bucket is per model (DEV run 1 headers)."""
    budget = TokenBudget(6500)

    assert budget.reserve("grounding", 6000, pool="openai/gpt-oss-20b")
    assert budget.reserve("correctness", 1400, pool="openai/gpt-oss-120b")
    assert not budget.reserve("test_coverage", 1000, pool="openai/gpt-oss-20b")
    assert budget.remaining_in("openai/gpt-oss-120b") == 5100
    assert budget.skipped == [
        (
            "test_coverage",
            "token budget exhausted (500 of 6500 left for openai/gpt-oss-20b, needed about 1000)",
        )
    ]


def test_the_pipeline_runs_correctness_beside_security_on_the_primary_model():
    served = []

    def complete(self, model, system_prompt, user_message, schema=None):
        served.append((model, system_prompt))
        if "classify" in system_prompt:
            return ProviderResponse('{"intent": "fix", "summary": "s"}', 10, 5), "groq", False
        if system_prompt == agent_prompts.CORRECTNESS_SYSTEM_PROMPT:
            payload = {
                "findings": [entry(8, INDEX_ERROR, "return (command.script.split()[1] == 'stash'")]
            }
            return ProviderResponse(json.dumps(payload), 700, 300), "groq", False
        return ProviderResponse('{"findings": []}', 10, 5), "groq", False

    with mock.patch.object(Runtime, "complete", complete):
        result = run_pipeline(DIFF, RepoContext("nvbn/thefuck", 0, ""), CONFIG)

    primary = [prompt for model, prompt in served if model == CONFIG.primary_model]
    assert agent_prompts.CORRECTNESS_SYSTEM_PROMPT in primary
    assert agent_prompts.SECURITY_SYSTEM_PROMPT in primary
    (finding,) = result.findings
    assert (finding.agent, finding.line, finding.severity) == (
        "correctness",
        8,
        Severity.BLOCKING,
    )
    assert not result.skipped_agents
