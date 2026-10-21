"""Synthesis: merge only real duplicates, never lose a distinct finding, keep a record.

The old rule merged anything within two lines. On testbed PR #5 that folded four raw
findings into one: grounding@6, security@7 ("db_path ... path traversal"),
security@6 ("no authorization checks") and a lint artefact F821@7. The db_path
finding disappeared, and the artefact was credited as "also flagged by
static_analysis".
"""

import json
from pathlib import Path
from unittest import mock

import pytest

from apps.agents import static_analysis, synthesis
from apps.agents.diffs import prepare
from apps.agents.graph import Runtime, run_pipeline
from apps.agents.nodes import exclude_own_changes
from apps.agents.providers import ProviderResponse
from apps.agents.types import (
    Category,
    Finding,
    Placement,
    RepoContext,
    RetrievedChunk,
    ReviewConfig,
    Severity,
)

FIXTURES = Path(__file__).parent / "fixtures" / "testbed"
PATH = "app/reports.py"


def make(
    agent,
    line,
    message,
    category=Category.SECURITY,
    severity=Severity.NIT,
    anchored_by="evidence",
    rule="",
):
    return Finding(
        file=PATH,
        line=line,
        severity=severity,
        category=category,
        message=message,
        agent=agent,
        placement=Placement.INLINE,
        anchored_by=anchored_by,
        rule=rule,
    )


SQLI = "customer_name is interpolated into the SQL query string, so a quote rewrites it."
B608 = make(
    "static_analysis",
    6,
    "bandit B608: Possible SQL injection vector through string-based query construction.",
    severity=Severity.BLOCKING,
    anchored_by="tool",
    rule="bandit B608",
)


# ------------------------------------------------------------------ the two cases


def test_a_lint_warning_near_a_test_coverage_finding_stays_separate():
    """PR #7: F841@6 was merged into test coverage's API_KEY finding at :4."""
    lint = make(
        "static_analysis",
        6,
        "ruff F841: Local variable `conn` is assigned to but never used",
        Category.CORRECTNESS,
        anchored_by="tool",
        rule="ruff F841",
    )
    coverage = make(
        "test_coverage", 3, "No test covers the empty API_KEY default.", Category.TESTING
    )
    same_line = make("test_coverage", 6, "No test covers the connection path.", Category.TESTING)

    final = synthesis.synthesise([lint, coverage, same_line])

    assert len(final) == 3
    assert not any("also flagged" in f.message for f in final)


def test_two_agents_flagging_the_same_sql_injection_merge():
    security = make("security", 6, SQLI, severity=Severity.BLOCKING)

    final, trace = synthesis.synthesise_traced([B608, security])

    assert len(final) == 1
    merged = final[0]
    assert merged.severity == Severity.BLOCKING
    # The explanation leads; the tool's rule id is still named.
    assert merged.message == f"{SQLI} (also flagged by static_analysis: bandit B608)"
    assert [(t.finding.agent, t.outcome) for t in trace] == [
        ("static_analysis", "merged"),
        ("security", "kept"),
    ]
    assert {t.final_index for t in trace} == {0}


# ------------------------------------------------------------- never lose one


def test_two_findings_from_one_agent_on_one_line_both_survive():
    path = make("security", 9, "db_path is passed straight to sqlite3.connect: path traversal.")
    authz = make("security", 9, "No authorization check before returning another user's orders.")

    assert len(synthesis.synthesise([path, authz])) == 2


def test_different_issues_on_one_line_survive_even_with_one_shared_word():
    injection = make("security", 6, SQLI)
    grounding = make(
        "grounding",
        6,
        "Duplicates the query helper `fetch_orders` in app/db.py.",
        Category.CORRECTNESS,
    )

    assert len(synthesis.synthesise([injection, grounding])) == 2


def test_same_issue_on_different_lines_is_not_merged():
    assert len(synthesis.synthesise([make("security", 6, SQLI), make("grounding", 7, SQLI)])) == 2


def test_a_verbatim_repeat_from_one_agent_collapses_without_a_credit():
    final = synthesis.synthesise([make("security", 6, SQLI), make("security", 6, f"  {SQLI} ")])

    assert len(final) == 1
    assert "also flagged" not in final[0].message


def test_tool_findings_merge_on_the_rule_id_not_the_wording():
    ruff = make("static_analysis", 6, "ruff S608: x", rule="ruff S608", anchored_by="tool")
    other = make("security", 6, "something else", rule="")

    assert len(synthesis.synthesise([ruff, other])) == 2
    assert len(synthesis.synthesise([ruff, make("grounding", 6, "y", rule="ruff S608")])) == 1


# ------------------------------------------------------------ representative


def test_the_representative_is_the_evidenced_definite_one_not_the_first():
    speculative = make("security", 6, f"{SQLI} It may be exploitable.", severity=Severity.NIT)
    guessed = make("grounding", 6, SQLI, anchored_by="snapped")
    definite = make("test_coverage", 6, SQLI, anchored_by="evidence")

    final = synthesis.synthesise([speculative, guessed, definite])

    assert len(final) == 1
    assert final[0].agent == "test_coverage"
    assert final[0].message.startswith(SQLI + " (also flagged by ")
    assert "security" in final[0].message and "grounding" in final[0].message


def test_findings_beyond_the_cap_are_traced_as_dropped():
    findings = [make("security", line, f"Defect number {line} here.") for line in range(1, 8)]

    final, trace = synthesis.synthesise_traced(findings, max_findings=5)

    assert len(final) == 5
    assert [t.reason for t in trace if t.outcome == "dropped"] == ["over the findings limit"] * 2


# ------------------------------------------------- grounding never cites the PR


def test_grounding_never_sees_chunks_of_the_prs_own_changes():
    prepared = prepare((FIXTURES / "pr5.diff.txt").read_text(encoding="utf-8"), 60_000)
    own = RetrievedChunk(PATH, "get_orders_by_customer", 5, 13, "def ...")
    elsewhere_in_file = RetrievedChunk(PATH, "find_customer", 21, 25, "def ...")
    other_file = RetrievedChunk("app/db.py", "fetch", 1, 30, "def ...")

    kept = exclude_own_changes([own, elsewhere_in_file, other_file], prepared)

    assert kept == [elsewhere_in_file, other_file]


# --------------------------------------------------- PR #5 through the pipeline


def entry(line, message, category="security", evidence="", severity="blocking"):
    return {
        "file": PATH,
        "line": line,
        "severity": severity,
        "category": category,
        "message": message,
        "evidence": evidence,
    }


def run_pr5(security=(), test_coverage=(), grounding=(), retrieved=()):
    def complete(self, model, system_prompt, user_message, schema=None):
        if "classify" in system_prompt:
            body = '{"intent": "fix", "summary": "s"}'
        elif "security reviewer" in system_prompt:
            body = json.dumps({"findings": list(security)})
        elif "test coverage" in system_prompt:
            body = json.dumps({"findings": list(test_coverage)})
        elif "already exists" in system_prompt:
            body = json.dumps({"findings": list(grounding)})
        else:
            body = '{"findings": []}'
        return ProviderResponse(body, 10, 5), "groq", False

    config = ReviewConfig(groq_api_key="k", gemini_api_key="k", backoff_seconds=0, max_retries=1)
    with (
        mock.patch.object(Runtime, "complete", complete),
        mock.patch("apps.agents.nodes.run_analysis", return_value=static_analysis.AnalysisReport()),
    ):
        return run_pipeline(
            (FIXTURES / "pr5.diff.txt").read_text(encoding="utf-8"),
            RepoContext("o/r", 5, "t"),
            config,
            retrieve=(lambda query: list(retrieved)) if retrieved else None,
        )


DB_PATH = (
    "The function accepts a db_path from the caller and passes it directly to "
    "sqlite3.connect, allowing path traversal or unauthorized file access if db_path "
    "is user-controlled."
)
AUTHZ = (
    "No authorization checks are performed before returning orders, potentially "
    "exposing data to unauthorized users."
)


def test_pr5_the_db_path_and_authorization_findings_stay_separate_and_unblocking():
    """The replayed raw output: both at lines near :6-7, neither with evidence."""
    result = run_pr5(security=[entry(7, DB_PATH), entry(6, AUTHZ)])

    messages = sorted(f.message for f in result.findings)
    assert messages == sorted([DB_PATH, AUTHZ])
    assert all(f.severity == Severity.NIT for f in result.findings)
    assert all(f.downgraded for f in result.findings)
    assert [t.outcome for t in result.trace] == ["kept", "kept"]


# --------------------------------------------------------------- persistence


@pytest.mark.django_db
def test_every_raw_finding_is_stored_with_what_became_of_it():
    from apps.reviews.models import ReviewRawFinding
    from apps.reviews.services import _store_findings, _store_trace
    from tests import factories

    result = run_pr5(
        security=[
            entry(7, DB_PATH, evidence="conn = sqlite3.connect(db_path)"),
            entry(9, SQLI, evidence='query = "SELECT * FROM orders WHERE customer = ?"'),
            entry(9, SQLI, evidence='query = "SELECT * FROM orders WHERE customer = ?"'),
            entry(3, "Not in this diff.", evidence="x = 1") | {"file": "app/other.py"},
        ],
        test_coverage=[
            entry(9, "No test for quotes in customer_name, which could expose SQL injection.")
        ],
    )
    _, org = factories.user("alice")
    review = factories.review(
        factories.pull_request(factories.repository(org, "alice/app"), 5, "t"), findings=()
    )
    final_rows = _store_findings(review, result.findings)
    _store_trace(review, result.trace, final_rows)

    rows = {
        (row.agent, row.cited_line, row.outcome): row
        for row in ReviewRawFinding.objects.filter(review=review)
    }
    assert len(rows) == 5

    db_path = rows[("security", 7, "kept")]
    assert (db_path.placement, db_path.severity, db_path.downgraded) == (
        "existing",
        "blocking",
        "about code this PR did not change",
    )
    assert db_path.final.message == DB_PATH

    kept = rows[("security", 9, "kept")]
    merged = rows[("security", 9, "merged")]
    assert merged.final_id == kept.final_id
    assert merged.reason.startswith("merged into security's finding")

    off_diff = rows[("security", 3, "dropped")]
    assert (off_diff.reason, off_diff.placement, off_diff.final) == (
        "off-diff: file is not in this diff",
        "",
        None,
    )
    scope = rows[("test_coverage", 9, "dropped")]
    assert scope.reason == "out of scope: test coverage making a security claim"
