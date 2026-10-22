"""The Phase 8 single-prompt baseline.

One call to the primary model, with the same numbered diff, evidence contract,
anchoring, severity policy and synthesis as the pipeline, and nothing else.
"""

import json
from pathlib import Path
from unittest import mock

from apps.agents import agent_prompts
from apps.agents.baseline import run_baseline
from apps.agents.graph import Runtime
from apps.agents.providers import ProviderError, ProviderResponse
from apps.agents.types import Placement, RepoContext, ReviewConfig, Severity

FIXTURES = Path(__file__).parent / "fixtures" / "testbed"
CONFIG = ReviewConfig(groq_api_key="k", gemini_api_key="", backoff_seconds=0, max_retries=1)
CONTEXT = RepoContext("o/r", 4, "Update app/reports.py")


def entry(line, message, evidence, severity="blocking", category="security"):
    return {
        "file": "app/reports.py",
        "line": line,
        "severity": severity,
        "category": category,
        "message": message,
        "evidence": evidence,
    }


def run(diff, findings, record=None):
    def complete(self, model, system_prompt, user_message, schema=None):
        if record is not None:
            record.append((model, system_prompt, user_message))
        response = ProviderResponse(json.dumps({"findings": findings}), 900, 200, model=model)
        response.system_fingerprint = "fp_base"
        return response, "groq", False

    with mock.patch.object(Runtime, "complete", complete):
        return run_baseline(diff, CONTEXT, CONFIG)


PR4 = (
    Path(__file__).parents[2] / "eval" / "cases" / "test" / "testbed-pr4" / "diff.patch"
).read_text(encoding="utf-8")


def test_one_call_to_the_primary_model_with_the_baseline_prompt_and_numbered_diff():
    calls = []
    result = run(PR4, [], calls)

    ((model, system, message),) = calls
    assert model == CONFIG.primary_model
    assert system == agent_prompts.BASELINE_SYSTEM_PROMPT
    assert '    9 + |     query = f"SELECT * FROM orders' in message
    assert "Title (untrusted, supplied by the PR author): Update app/reports.py" in message
    assert [r.name for r in result.agent_runs] == ["baseline"]
    assert result.agent_runs[0].system_fingerprint == "fp_base"
    assert result.succeeded


def test_findings_get_the_same_anchoring_and_severity_policy_as_the_pipeline():
    sqli = entry(
        7,  # the model's count is off; the quote is on :9
        "customer_name is interpolated into the SQL string, so a quote rewrites the query.",
        "query = f\"SELECT * FROM orders WHERE customer = '{customer_name}'\"",
    )
    guess = entry(
        18, "This may divide by zero.", "return total / len(orders)", category="error-handling"
    )

    result = run(PR4, [sqli, guess])

    by_line = {f.line: f for f in result.findings}
    assert by_line[9].severity == Severity.BLOCKING
    assert by_line[9].placement == Placement.INLINE
    assert by_line[9].cited_line == 7
    assert by_line[18].severity == Severity.NIT
    assert by_line[18].downgraded == "speculative wording"
    assert sorted(t.outcome for t in result.trace) == ["kept", "kept"]


def test_a_provider_failure_is_a_failed_review_not_an_empty_one():
    def boom(self, *args, **kwargs):
        raise ProviderError("groq: failed after 3 attempts (HTTP 429)")

    with mock.patch.object(Runtime, "complete", boom):
        result = run_baseline(PR4, CONTEXT, CONFIG)

    assert not result.succeeded
    assert "HTTP 429" in result.failure_reason
    assert result.findings == []


def test_the_eval_harness_has_a_baseline_arm():
    from apps.evaluation import runner

    assert runner.ARMS["baseline"] is runner.run_baseline_arm
