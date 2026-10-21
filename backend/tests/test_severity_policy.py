"""Severity policy: blocking is earned, not asserted.

On the testbed runs 73% of findings were blocking and test coverage produced 27 of
the 38 blocking ones. These run mocked agent outputs through the real pipeline, so
anchoring, the policy and synthesis all apply exactly as in a review.
"""

import json
from pathlib import Path
from unittest import mock

import pytest

from apps.agents import policy, static_analysis
from apps.agents.diffs import prepare
from apps.agents.graph import Runtime, run_pipeline
from apps.agents.nodes import static_analysis as static_analysis_node
from apps.agents.providers import ProviderResponse
from apps.agents.types import Category, Finding, Placement, RepoContext, ReviewConfig, Severity

FIXTURES = Path(__file__).parent / "fixtures" / "testbed"
PATH = "app/reports.py"

# Testbed PR #4's shape: a new file whose query is built with an f-string.
SQL_INJECTION_DIFF = """diff --git a/app/reports.py b/app/reports.py
new file mode 100644
--- /dev/null
+++ b/app/reports.py
@@ -0,0 +1,7 @@
+import sqlite3
+
+
+def get_orders_by_customer(db_path, customer_name):
+    conn = sqlite3.connect(db_path)
+    query = f"SELECT * FROM orders WHERE customer = '{customer_name}'"
+    return conn.execute(query).fetchall()
"""


def fixture_diff(name):
    return (FIXTURES / f"{name}.diff.txt").read_text(encoding="utf-8")


def entry(line, message, evidence="", severity="blocking", category="testing"):
    return {
        "file": PATH,
        "line": line,
        "severity": severity,
        "category": category,
        "message": message,
        "evidence": evidence,
    }


def review(diff, security=(), test_coverage=()):
    """Run the pipeline with these agent outputs; linters and grounding find nothing."""

    def complete(self, model, system_prompt, user_message, schema=None):
        if "classify" in system_prompt:
            body = '{"intent": "fix", "summary": "s"}'
        elif "security reviewer" in system_prompt:
            body = json.dumps({"findings": list(security)})
        elif "test coverage" in system_prompt:
            body = json.dumps({"findings": list(test_coverage)})
        else:
            body = '{"findings": []}'
        return ProviderResponse(body, 10, 5), "groq", False

    config = ReviewConfig(groq_api_key="k", gemini_api_key="k", backoff_seconds=0, max_retries=1)
    with (
        mock.patch.object(Runtime, "complete", complete),
        mock.patch("apps.agents.nodes.run_analysis", return_value=static_analysis.AnalysisReport()),
    ):
        return run_pipeline(diff, RepoContext("o/r", 1, "t"), config)


def only(result):
    assert len(result.findings) == 1, result.findings
    return result.findings[0]


# ------------------------------------------------------- the four required cases


def test_a_test_coverage_finding_is_never_blocking():
    """PR #7: "no test covers the empty-list case" was blocking."""
    result = review(
        fixture_diff("pr7"),
        test_coverage=[
            entry(15, "No test covers average_order_value with an empty list.", "if not orders:")
        ],
    )

    found = only(result)
    assert (found.line, found.severity) == (17, Severity.NIT)
    assert found.downgraded == "test coverage is never blocking"


def test_pr5_db_path_may_be_untrusted_is_a_nit():
    """PR #5: speculative, and about a line the PR did not change."""
    message = (
        "The function uses sqlite3.connect(db_path) with a db_path parameter that may be "
        "supplied by an untrusted source, potentially allowing path traversal."
    )
    result = review(
        fixture_diff("pr5"),
        security=[entry(6, message, "conn = sqlite3.connect(db_path)", category="security")],
    )

    found = only(result)
    assert found.severity == Severity.NIT
    assert found.placement == Placement.EXISTING
    assert found.downgraded == "about code this PR did not change"


def test_speculation_alone_downgrades_even_on_an_added_line():
    message = "If customer_name is user-controlled this could allow injection."
    evidence = """query = f"SELECT * FROM orders WHERE customer = '{customer_name}'\""""
    result = review(SQL_INJECTION_DIFF, security=[entry(6, message, evidence, category="security")])

    found = only(result)
    assert (found.placement, found.severity) == (Placement.INLINE, Severity.NIT)
    assert found.downgraded == "speculative wording"


def test_an_unchanged_line_finding_goes_to_the_existing_code_section():
    """PR #6: the hard-coded key is on :3, which PR #6 did not change."""
    from types import SimpleNamespace

    from apps.reviews import comment

    result = review(
        fixture_diff("pr6"),
        security=[
            entry(
                3,
                "A live API key is committed to source.",
                'API_KEY = "sk-live-9f8a7b6c5d4e3f2a1b0c"',
                category="security",
            )
        ],
    )
    found = only(result)
    assert (found.placement, found.severity) == (Placement.EXISTING, Severity.NIT)

    row = SimpleNamespace(
        file_path=found.file,
        line=found.line,
        severity=str(found.severity),
        category=str(found.category),
        message=found.message,
        placement=str(found.placement),
    )
    body = comment.render(
        SimpleNamespace(
            head_sha="d8a835e",
            duration_ms=1,
            estimated_cost_inr=0,
            model_used="m",
            used_fallback=False,
            truncated=False,
            skipped_files=[],
        ),
        [row],
    )
    assert "<summary>Existing code (not introduced by this PR) · 1</summary>" in body
    assert "blocking" not in body.lower().split("<details>")[0]


def test_a_real_sql_injection_on_an_added_line_stays_blocking():
    message = (
        "customer_name is interpolated into the SQL string with an f-string, so a quote "
        "in it rewrites the query (SQL injection). Use a parameterised query."
    )
    evidence = """query = f"SELECT * FROM orders WHERE customer = '{customer_name}'\""""
    result = review(SQL_INJECTION_DIFF, security=[entry(6, message, evidence, category="security")])

    found = only(result)
    assert (found.line, found.placement, found.severity) == (6, Placement.INLINE, Severity.BLOCKING)
    assert found.downgraded == ""


# --------------------------------------------------------------------- scope


def test_test_coverage_claiming_a_security_issue_is_dropped():
    """PR #5 replay: "could expose SQL injection" on the line that fixes it."""
    message = (
        "No tests cover get_orders_by_customer with quotes in customer_name, which could "
        "expose SQL injection vulnerability if not parameterized."
    )
    result = review(
        fixture_diff("pr5"),
        test_coverage=[entry(9, message, 'query = "SELECT * FROM orders WHERE customer = ?"')],
    )

    assert result.findings == []
    assert [(f.agent, why) for f, why in result.dropped] == [
        ("test_coverage", "out of scope: test coverage making a security claim")
    ]


def test_a_security_agent_finding_outside_security_is_dropped():
    result = review(
        fixture_diff("pr7"),
        security=[
            entry(17, "Returns 0 instead of None.", "if not orders:", category="correctness")
        ],
    )

    assert result.findings == []
    assert result.dropped[0][1] == "out of scope: security reporting correctness"


def test_test_coverage_findings_are_filed_as_testing_whatever_it_said():
    """Review 42 had a test-coverage finding labelled "correctness"."""
    result = review(
        fixture_diff("pr7"),
        test_coverage=[
            entry(
                4,
                "API_KEY default empty string not covered by tests",
                'API_KEY = os.environ.get("REPORTS_API_KEY", "")',
                category="correctness",
            )
        ],
    )

    assert only(result).category == Category.TESTING


# ------------------------------------------------------------------- linters


def tool_finding(rule, line=6):
    return Finding(
        file=PATH,
        line=line,
        severity=Severity.BLOCKING,
        category=Category.SECURITY,
        message="m",
        agent="static_analysis",
        placement=Placement.INLINE,
        anchored_by="tool",
        rule=rule,
    )


@pytest.mark.parametrize(
    ("rule", "severity"),
    [("bandit B608", Severity.BLOCKING), ("ruff S608", Severity.NIT), ("ruff F401", Severity.NIT)],
)
def test_only_bandit_may_make_a_tool_finding_blocking(rule, severity):
    assert policy.cap(tool_finding(rule)).severity == severity


@pytest.mark.skipif(static_analysis.tool_command("bandit") is None, reason="bandit missing")
def test_real_linters_on_an_f_string_query_block_only_through_bandit():
    out = static_analysis_node({"prepared": prepare(SQL_INJECTION_DIFF, 60_000)})
    by_rule = {f.rule: f.severity for f in out["findings"]}

    assert by_rule.get("bandit B608") == Severity.BLOCKING
    assert all(sev == Severity.NIT for rule, sev in by_rule.items() if rule.startswith("ruff"))


# ------------------------------------------------------------------ wording


@pytest.mark.parametrize(
    "message",
    [
        "db_path may be supplied by an untrusted source",
        "This could allow path traversal",
        "potentially exposing data to unauthorized users",
        "if db_path is user-controlled an attacker can read any file",
        "If the input is untrusted, this is injectable",
    ],
)
def test_speculative_wording_is_recognised(message):
    assert policy.SPECULATIVE.search(message)


@pytest.mark.parametrize(
    "message",
    [
        "customer_name is interpolated into the SQL string, so a quote rewrites the query",
        "conn is never closed when cursor.execute raises",
        "Returns None when no customer matches, and the caller indexes into it",
    ],
)
def test_definite_findings_are_not_speculative(message):
    assert not policy.SPECULATIVE.search(message)
