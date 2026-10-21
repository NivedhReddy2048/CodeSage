"""Evidence-based anchoring: a finding lands on the line it quotes, not the line a
model counted to.

Regression fixtures are the real diffs of testbed PRs #5, #6 and #7, and the wrong
lines the agents actually cited on them (Step 0 investigation):

  PR #7  :4 and :2 for the API_KEY change on :3; :15 and :14 for the empty-list
         guard on :17-18 - all blank or unchanged lines.
  PR #6  :11 for "the finally block is not covered"; `finally:` is :12. And the
         hard-coded key on :3, a line the PR did not change.
  PR #5  :6 (the `def` line) for `sqlite3.connect(db_path)`, which is unchanged :7.
"""

from pathlib import Path

import pytest

from apps.agents.anchoring import anchor, anchor_all, normalise
from apps.agents.diffs import numbered_diff, prepare
from apps.agents.types import Category, Finding, Placement, Severity

FIXTURES = Path(__file__).parent / "fixtures" / "testbed"
PATH = "app/reports.py"


def diff(name):
    return prepare((FIXTURES / f"{name}.diff.txt").read_text(encoding="utf-8"), 60_000)


def finding(line, evidence="", path=PATH, agent="test_coverage"):
    return Finding(
        file=path,
        line=line,
        severity=Severity.NIT,
        category=Category.TESTING,
        message="m",
        agent=agent,
        evidence=evidence,
    )


def placed(prepared, line, evidence=""):
    result = anchor(finding(line, evidence), prepared)
    return result.line, str(result.placement), result.anchored_by


# --------------------------------------------------------------- what agents see


def test_the_numbered_diff_prints_every_line_number_and_marker():
    text = numbered_diff(diff("pr7"))

    assert "=== app/reports.py ===" in text
    assert '    3 + | API_KEY = os.environ.get("REPORTS_API_KEY", "")' in text
    assert "    4   | " in text  # the blank context line the agent cited
    assert "   17 + |     if not orders:" in text
    # A removed line has no new-file number to cite.
    assert '      - | API_KEY = "sk-live-9f8a7b6c5d4e3f2a1b0c"' in text


def test_the_security_and_test_prompts_ask_for_evidence_on_the_numbered_diff():
    from apps.agents import agent_prompts
    from apps.agents.schema import RESPONSE_SCHEMA

    message = agent_prompts.build_test_message(diff("pr7"), "")

    assert "   17 + |     if not orders:" in message
    assert "app/reports.py: lines 1, 3, 17-18" in message  # added lines only
    for prompt in (agent_prompts.SECURITY_SYSTEM_PROMPT, agent_prompts.TEST_SYSTEM_PROMPT):
        assert "evidence" in prompt and "Never count lines yourself" in prompt
    assert "evidence" in RESPONSE_SCHEMA["properties"]["findings"]["items"]["required"]


# ------------------------------------------------------------- testbed PR #7


@pytest.mark.parametrize("cited", [4, 2])
def test_pr7_the_api_key_finding_lands_on_line_3(cited):
    evidence = 'API_KEY = os.environ.get("REPORTS_API_KEY", "")'
    assert placed(diff("pr7"), cited, evidence) == (3, "inline", "evidence")


@pytest.mark.parametrize("cited", [15, 14])
def test_pr7_the_empty_list_finding_lands_on_line_17(cited):
    assert placed(diff("pr7"), cited, "if not orders:") == (17, "inline", "evidence")


@pytest.mark.parametrize(
    ("cited", "expected"),
    [(4, 3), (15, 17), (14, 17), (6, 3)],
)
def test_pr7_without_evidence_a_near_miss_snaps_within_its_hunk(cited, expected):
    assert placed(diff("pr7"), cited) == (expected, "inline", "snapped")


def test_pr7_a_quote_copied_with_its_number_and_marker_still_matches():
    prepared = diff("pr7")

    assert placed(prepared, 15, "   17 + |     if not orders:")[:2] == (17, "inline")
    assert placed(prepared, 15, "+    if not orders:")[:2] == (17, "inline")


def test_pr7_a_multi_line_quote_lands_on_the_quoted_line_nearest_the_citation():
    evidence = "if not orders:\n    return 0"

    assert placed(diff("pr7"), 15, evidence)[:2] == (17, "inline")
    assert placed(diff("pr7"), 20, evidence)[:2] == (18, "inline")


# ------------------------------------------------------------- testbed PR #6


def test_pr6_the_finally_finding_lands_on_line_12():
    assert placed(diff("pr6"), 11, "finally:") == (12, "inline", "evidence")


def test_pr6_the_hard_coded_key_is_existing_code_not_inline():
    """:3 is unchanged in PR #6: the author did not write it."""
    evidence = 'API_KEY = "sk-live-9f8a7b6c5d4e3f2a1b0c"'

    assert placed(diff("pr6"), 3, evidence) == (3, "existing", "evidence")


def test_pr6_the_key_finding_without_evidence_is_general():
    """:3 is context and the nearest added line (:7) is four away."""
    assert placed(diff("pr6"), 3) == (3, "general", "")


# ------------------------------------------------------------- testbed PR #5


def test_pr5_the_db_path_finding_is_about_unchanged_line_7():
    assert placed(diff("pr5"), 6, "conn = sqlite3.connect(db_path)") == (7, "existing", "evidence")


def test_pr5_evidence_beats_the_cited_number():
    """Cited :9 (an added line), but quotes :10."""
    evidence = "cursor.execute(query, (customer_name,))"

    assert placed(diff("pr5"), 9, evidence) == (10, "inline", "evidence")


# ------------------------------------------------------------------ the rules


def test_evidence_that_matches_nothing_falls_back_to_the_cited_line():
    prepared = diff("pr7")

    assert placed(prepared, 17, "something the diff never said") == (17, "inline", "cited")
    assert placed(prepared, 15, "something the diff never said")[:2] == (17, "inline")


def test_a_short_quote_must_match_a_whole_line():
    """ "return 0" is short; it may not match inside a longer line."""
    assert placed(diff("pr7"), 15, "return 0")[:2] == (18, "inline")
    assert placed(diff("pr7"), 3, "os")[2] == "cited"  # too short to be a fragment


def test_an_added_line_beats_an_unchanged_one_with_the_same_text():
    text = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
        "@@ -1,3 +1,4 @@\n"
        " value = compute()\n"
        " other = 1\n"
        "+value = compute()\n"
        " end = 2\n"
    )
    result = anchor(finding(1, "value = compute()", path="a.py"), prepare(text, 10_000))

    assert (result.line, str(result.placement), result.anchored_by) == (3, "inline", "evidence")


def test_a_finding_far_from_any_added_line_is_general():
    assert placed(diff("pr7"), 9999) == (9999, "general", "")


def test_a_finding_about_a_file_not_in_the_diff_is_dropped():
    assert anchor_all([finding(3, path="app/other.py")], diff("pr7")) == []


def test_allows_accepts_only_added_lines():
    prepared = diff("pr7")

    assert [n for n in range(1, 22) if prepared.allows(PATH, n)] == [1, 3, 17, 18]


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        ("  17 + |     if not orders:", "if not orders:"),
        ("+    if not orders:", "if not orders:"),
        ("x  =   a  |  b", "x = a | b"),
    ],
)
def test_normalise_strips_copied_prefixes_but_not_code(quote, expected):
    assert normalise(quote) == expected


# ------------------------------------------------- summary and inline agree


@pytest.mark.django_db
def test_the_summary_names_exactly_the_line_the_inline_comment_is_on():
    """PR #7 end to end from stored findings: no :4, no :15, anywhere."""
    from types import SimpleNamespace

    from apps.reviews import comment
    from apps.reviews.inline import post_inline_comments
    from apps.reviews.models import Review
    from apps.reviews.services import _store_findings
    from tests import factories

    _, org = factories.user("alice")
    pr = factories.pull_request(factories.repository(org, "alice/app"), 7, "PR")
    review = factories.review(pr, findings=())
    found = anchor_all(
        [
            finding(4, 'API_KEY = os.environ.get("REPORTS_API_KEY", "")'),
            finding(15, "if not orders:"),
            finding(9999),
        ],
        diff("pr7"),
    )
    rows = _store_findings(review, found)

    posted = []
    github = SimpleNamespace(
        list_review_comments=lambda *a: [],
        create_review=lambda *a: posted.extend(a[-1]) or {"id": 1},
    )
    post_inline_comments(github, 1, pr, "abc", rows, 15)
    body = comment.render(Review.objects.get(pk=review.pk), rows)

    assert sorted(c["line"] for c in posted) == [3, 17]
    assert "`app/reports.py:3`" in body and "`app/reports.py:17`" in body
    assert ":4`" not in body and ":15`" not in body
    # The unplaceable one is summarised under General, without a made-up line.
    assert "### General" in body and "`app/reports.py`" in body
    assert ":9999" not in body
    assert [r.placement for r in rows] == [
        Placement.INLINE,
        Placement.INLINE,
        Placement.GENERAL,
    ]
