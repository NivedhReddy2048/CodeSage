"""Static analysis lints the real file, and reports only on lines the PR added.

Regression for testbed PRs #5 and #7. A modified file was linted as a reconstruction
of its hunks, which is missing everything outside them, so ruff reported problems
that exist only in that reconstruction:

  PR #5: F821 "Undefined name `sqlite3`" at :7 - `import sqlite3` is on :1, outside
         the hunk.
  PR #7: F841 "Local variable `conn` is assigned to but never used" at :6 - the rest
         of the function is outside the hunk.

Both sat on unchanged context lines, passed the "lines the PR touched" filter
because that accepted context, and were then merged into unrelated findings.
"""

from pathlib import Path
from unittest import mock

import pytest

from apps.agents import static_analysis
from apps.agents.diffs import prepare
from apps.agents.graph import Runtime
from apps.agents.nodes import static_analysis as static_analysis_node
from apps.agents.static_analysis import AnalysisReport, ToolFinding
from apps.agents.types import ReviewConfig

FIXTURES = Path(__file__).parent / "fixtures" / "testbed"
PATH = "app/reports.py"

needs_ruff = pytest.mark.skipif(
    static_analysis.tool_command("ruff") is None, reason="ruff is not installed"
)


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def run_node(diff, fetch_source=None, max_source_bytes=256 * 1024):
    state = {"prepared": prepare(diff, 60_000)}
    if fetch_source is not None:
        state["runtime"] = Runtime(
            ReviewConfig(max_source_bytes=max_source_bytes), fetch_source=fetch_source
        )
    result = static_analysis_node(state)
    return result["findings"], result["runs"][0]


def codes(findings):
    return {f.message.rsplit(" ", 1)[-1].rstrip(")") for f in findings}


# --------------------------------------------------------------------- added lines


@pytest.mark.parametrize(
    ("name", "expected"),
    [("pr5", {9, 10}), ("pr6", set(range(7, 14))), ("pr7", {1, 3, 17, 18})],
)
def test_added_lines_are_only_the_plus_lines(name, expected):
    entry = prepare(fixture(f"{name}.diff.txt"), 60_000).files[0]

    assert entry.added_lines == expected
    # Context lines are still in the diff, just not the author's change.
    assert entry.added_lines < entry.changed_lines


# ------------------------------------------------------- the testbed regressions


@needs_ruff
@pytest.mark.parametrize("name", ["pr5", "pr7"])
def test_the_real_file_produces_no_partial_context_artefacts(name):
    fetched = []

    def fetch(path):
        fetched.append(path)
        return fixture(f"{name}.reports.py.txt")

    findings, run = run_node(fixture(f"{name}.diff.txt"), fetch)

    assert fetched == [PATH]
    assert not codes(findings) & {"F821", "F841"}
    assert run.succeeded
    assert "hunks only" not in run.detail


@needs_ruff
@pytest.mark.parametrize("name", ["pr5", "pr7"])
def test_without_the_real_file_the_artefact_rules_are_suppressed(name):
    findings, run = run_node(fixture(f"{name}.diff.txt"))

    assert not codes(findings) & {"F821", "F841"}
    assert run.detail.endswith("1 file(s) from diff hunks only")


@needs_ruff
@pytest.mark.parametrize("failure", [None, "raise", "too big"])
def test_a_failed_fetch_falls_back_to_the_hunks(failure):
    def fetch(path):
        if failure == "raise":
            raise RuntimeError("GitHub is down")
        return None if failure is None else fixture("pr7.reports.py.txt")

    findings, run = run_node(fixture("pr7.diff.txt"), fetch, max_source_bytes=100)

    assert not codes(findings) & {"F821", "F841"}
    assert run.succeeded
    assert "hunks only" in run.detail


@needs_ruff
def test_the_real_file_still_catches_context_rules_on_added_lines():
    """The point of fetching: an unused import the PR added is now visible.

    PR #7 adds `import os` on :1. Change the head so nothing uses it, and ruff can
    only say F401 if it sees the whole file - in a reconstruction that rule is off.
    """
    head = fixture("pr7.reports.py.txt").replace('os.environ.get("REPORTS_API_KEY", "")', '""')
    diff = fixture("pr7.diff.txt").replace('os.environ.get("REPORTS_API_KEY", "")', '""')

    with_file, _ = run_node(diff, lambda path: head)
    without_file, _ = run_node(diff)

    unused = [f for f in with_file if "F401" in f.message]
    assert [(f.line, f.agent) for f in unused] == [(1, "static_analysis")]
    assert "ruff F401" in unused[0].message
    assert not [f for f in without_file if "F401" in f.message]


# ---------------------------------------------------------- only on added lines


def test_tool_findings_off_added_lines_are_dropped_not_moved():
    """A tool names the exact line it means; moving it would misattribute it."""
    report = AnalysisReport(
        ran=["ruff"],
        findings=[
            ToolFinding(PATH, 6, "F841", "Local variable `conn` unused", "ruff"),  # context
            ToolFinding(PATH, 4, "S105", "Possible hardcoded password", "ruff", "blocking"),
            ToolFinding(PATH, 3, "S105", "Possible hardcoded password", "ruff", "blocking"),
        ],
    )
    with mock.patch("apps.agents.nodes.run_analysis", return_value=report):
        findings, _ = run_node(fixture("pr7.diff.txt"))

    # :6 is context and :4 a blank context line; only :3 was added by the PR.
    assert [(f.line, f.message) for f in findings] == [
        (3, "ruff S105: Possible hardcoded password")
    ]


def test_an_added_file_is_never_fetched():
    """Its hunks already are the whole file, so there is nothing to gain."""
    diff = (
        "diff --git a/app/new.py b/app/new.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/app/new.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+import os\n"
        "+print(os.sep)\n"
    )
    fetch = mock.Mock(return_value="should not be used")

    _, run = run_node(diff, fetch)

    fetch.assert_not_called()
    assert "hunks only" not in run.detail
