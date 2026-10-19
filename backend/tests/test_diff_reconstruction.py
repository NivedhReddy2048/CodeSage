"""Reconstructing the post-change file from a diff, for the linters.

This is the input to every static-analysis finding, so an error here is not a missed
finding - it is a confident finding about the wrong line, or about code nobody wrote.
Both shipped: see issue #47.
"""

import textwrap
from unittest import mock

import pytest

from apps.agents import static_analysis
from apps.agents.diffs import (
    MAX_RECONSTRUCTED_LINES,
    adds_whole_file,
    prepare,
    reconstruct_new_file,
)
from apps.agents.nodes import static_analysis as static_analysis_node
from apps.agents.types import PreparedDiff

MAX_BYTES = 60_000


def section(diff_text):
    prepared = prepare(diff_text, MAX_BYTES)
    assert prepared.files, "diff did not parse into a file section"
    return prepared, prepared.files[0]


# ======================================================== git's extended headers


ADDED_FILE = """diff --git a/app/lookup.py b/app/lookup.py
new file mode 100644
index 0000000..7db11c6
--- /dev/null
+++ b/app/lookup.py
@@ -0,0 +1,3 @@
+def lookup_user(users, user_id):
+    \"\"\"Find a user by id.\"\"\"
+    return None
"""


def test_new_file_mode_never_reaches_the_source():
    """The bug behind issue #47: it became line 1 of the Python given to ruff.

    Which is a syntax error in a file that has none, and shifts every line number
    after it by one.
    """
    _, entry = section(ADDED_FILE)
    text = reconstruct_new_file(entry.text)

    assert "new file mode" not in text
    assert text.splitlines()[0] == "def lookup_user(users, user_id):"
    compile(text, entry.path, "exec")  # the real test: it parses


def test_every_extended_header_is_excluded_not_just_the_known_ones():
    """A prefix blacklist misses whichever header it was not told about.

    So reconstruction reads hunk bodies only, and this asserts the property rather
    than a list: nothing before the first `@@` can appear in the output.
    """
    headers = [
        "old mode 100644",
        "new mode 100755",
        "deleted file mode 100644",
        "similarity index 94%",
        "rename from app/old.py",
        "rename to app/new.py",
        "copy from app/a.py",
        "copy to app/b.py",
        "GIT binary patch",
    ]
    diff = (
        "diff --git a/app/x.py b/app/x.py\n"
        + "\n".join(headers)
        + "\n--- a/app/x.py\n+++ b/app/x.py\n@@ -1,1 +1,1 @@\n+x = 1\n"
    )

    text = reconstruct_new_file(section(diff)[1].text)

    assert text.strip() == "x = 1"
    for header in headers:
        assert header not in text


# ============================================================== line numbering


LATE_HUNK = """diff --git a/app/users.py b/app/users.py
index 1111111..2222222 100644
--- a/app/users.py
+++ b/app/users.py
@@ -51,5 +51,6 @@ def earlier():
 def paginate_users(users, page, per_page=10):
     start = (page - 1) * per_page
-    end = page + per_page
+    end = start + per_page
+    import os
     return users[start:end]
"""


def test_a_line_sits_at_its_line_number_in_the_new_file():
    """A hunk starts where its header says, not at line 1.

    Reconstructing 1-based meant ruff reported line 5 for line 55. `allows` then
    rejected it, so the finding vanished - or, worse, the number landed inside the
    allowed set and the comment was anchored to unrelated code.
    """
    prepared, entry = section(LATE_HUNK)
    lines = reconstruct_new_file(entry.text).splitlines()

    assert lines[50] == "def paginate_users(users, page, per_page=10):"
    assert lines[53] == "    import os"
    assert lines[:50] == [""] * 50  # the untouched head of the file, padded


def test_every_reconstructed_line_is_one_the_diff_allows():
    """The two must agree, or static analysis silently drops its own findings."""
    prepared, entry = section(LATE_HUNK)

    for number, line in enumerate(reconstruct_new_file(entry.text).splitlines(), start=1):
        if line.strip():
            assert prepared.allows(entry.path, number), f"line {number} not allowed"


def test_separate_hunks_each_land_at_their_own_numbers():
    diff = textwrap.dedent(
        """\
        diff --git a/app/x.py b/app/x.py
        --- a/app/x.py
        +++ b/app/x.py
        @@ -3,1 +3,1 @@
        +first = 1
        @@ -40,1 +40,1 @@
        +second = 2
        """
    )

    lines = reconstruct_new_file(section(diff)[1].text).splitlines()

    assert lines[2] == "first = 1"
    assert lines[39] == "second = 2"
    assert lines[3:39] == [""] * 36


def test_removed_lines_are_not_in_the_new_file():
    lines = reconstruct_new_file(section(LATE_HUNK)[1].text).splitlines()

    assert "    end = page + per_page" not in lines
    assert "    end = start + per_page" in lines


def test_an_absurd_hunk_header_cannot_exhaust_memory():
    """A hunk header is attacker-controlled, and padding obeys it.

    `@@ -0,0 +99999999,1 @@` is a one-line diff asking for a hundred million lines.
    """
    diff = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -0,0 +99999999,1 @@\n+x = 1\n"

    text = reconstruct_new_file(section(diff)[1].text)

    assert len(text.splitlines()) <= MAX_RECONSTRUCTED_LINES


# ======================================================= whole file or a fragment


def test_an_added_file_is_recognised_as_whole():
    assert adds_whole_file(ADDED_FILE) is True
    assert section(ADDED_FILE)[1].is_new_file is True


def test_a_dev_null_source_is_recognised_as_whole():
    diff = "diff --git a/a.py b/a.py\n--- /dev/null\n+++ b/a.py\n@@ -0,0 +1,1 @@\n+x = 1\n"

    assert adds_whole_file(diff) is True


def test_a_modified_file_is_a_fragment():
    assert adds_whole_file(LATE_HUNK) is False
    assert section(LATE_HUNK)[1].is_new_file is False


def test_hunk_content_is_never_mistaken_for_a_header():
    """A diff that adds the literal text `new file mode` adds a line, not a header."""
    diff = (
        "diff --git a/a.py b/a.py\nindex 1..2 100644\n--- a/a.py\n+++ b/a.py\n"
        '@@ -1,1 +1,1 @@\n+mode = "new file mode 100644"\n'
    )

    assert adds_whole_file(diff) is False
    assert 'mode = "new file mode 100644"' in reconstruct_new_file(section(diff)[1].text)


# ====================================================== syntax diagnostics


def test_syntax_codes_are_recognised_across_ruff_versions():
    for code in ("invalid-syntax", "E999", "E9", "", None):
        assert static_analysis.is_syntax_code(code), repr(code)
    for code in ("F401", "S307", "B008", "RUF001"):
        assert not static_analysis.is_syntax_code(code)


def ruff_saying_invalid_syntax(workdir_files):
    """A fake `ruff check --output-format json` reporting one syntax error."""
    name = next(iter(workdir_files))
    return mock.Mock(
        stdout=f"""[{{"filename": "{name}", "code": "invalid-syntax",
        "message": "Unexpected indentation", "location": {{"row": 1}}}}]"""
    )


def test_a_fragment_that_does_not_parse_is_not_reported():
    """Hunks from inside a class body reconstruct as indented top-level code.

    Calling that a syntax error describes our reconstruction, not the pull request.
    """
    with (
        mock.patch("apps.agents.static_analysis.tool_command", side_effect=lambda m: [m]),
        mock.patch("apps.agents.static_analysis._run") as run,
    ):
        run.side_effect = lambda command, cwd: (
            mock.Mock(
                stdout='[{"filename": "f0_x.py", "code": "invalid-syntax",'
                ' "message": "Unexpected indentation", "location": {"row": 1}}]'
            )
            if command[0] == "ruff"
            else mock.Mock(stdout='{"results": []}')
        )
        findings = static_analysis.analyse({"app/x.py": "    indented = 1\n"}, complete=())

    assert findings == []


def test_a_whole_file_that_does_not_parse_is_reported():
    """Testbed PR #1 really is broken Python, and a reviewer should be told."""
    with (
        mock.patch("apps.agents.static_analysis.tool_command", side_effect=lambda m: [m]),
        mock.patch("apps.agents.static_analysis._run") as run,
    ):
        run.side_effect = lambda command, cwd: (
            mock.Mock(
                stdout='[{"filename": "f0_x.py", "code": "invalid-syntax",'
                ' "message": "Unexpected indentation", "location": {"row": 1}}]'
            )
            if command[0] == "ruff"
            else mock.Mock(stdout='{"results": []}')
        )
        findings = static_analysis.analyse(
            {"app/x.py": "    indented = 1\n"}, complete={"app/x.py"}
        )

    assert [f.code for f in findings] == ["invalid-syntax"]


def test_a_real_defect_is_reported_in_a_fragment():
    """Suppressing syntax noise must not suppress the findings that matter."""
    with (
        mock.patch("apps.agents.static_analysis.tool_command", side_effect=lambda m: [m]),
        mock.patch("apps.agents.static_analysis._run") as run,
    ):
        run.side_effect = lambda command, cwd: (
            mock.Mock(
                stdout='[{"filename": "f0_x.py", "code": "S307",'
                ' "message": "Use of possibly insecure function", "location": {"row": 54}}]'
            )
            if command[0] == "ruff"
            else mock.Mock(stdout='{"results": []}')
        )
        findings = static_analysis.analyse({"app/x.py": "x = 1\n"}, complete=())

    assert [(f.code, f.line) for f in findings] == [("S307", 54)]


# ================================================================== the node


def test_the_node_hands_the_linters_whole_files_and_marks_them():
    """End to end through the agent: no header leak, and completeness passed on."""
    prepared = prepare(ADDED_FILE + LATE_HUNK, MAX_BYTES)
    assert len(prepared.files) == 2

    with mock.patch(
        "apps.agents.nodes.run_analysis",
        return_value=static_analysis.AnalysisReport(ran=["ruff"]),
    ) as analyse:
        static_analysis_node({"prepared": prepared})

    contents, kwargs = analyse.call_args.args[0], analyse.call_args.kwargs
    assert kwargs["complete"] == {"app/lookup.py"}
    assert "new file mode" not in contents["app/lookup.py"]
    compile(contents["app/lookup.py"], "app/lookup.py", "exec")
    assert contents["app/users.py"].splitlines()[53] == "    import os"


@pytest.mark.skipif(static_analysis.tool_command("ruff") is None, reason="ruff is not installed")
def test_real_ruff_findings_land_on_lines_the_diff_allows():
    """The whole fix, against the real tool rather than a mock.

    This diff adds a SQL-injection string on line 13 of a modified file. Before the
    fix, ruff reported it on line 4 of a 1-based reconstruction, `allows` rejected
    that, and two real findings were dropped without a trace.
    """
    diff = textwrap.dedent(
        """\
        diff --git a/app/users.py b/app/users.py
        --- a/app/users.py
        +++ b/app/users.py
        @@ -10,6 +10,8 @@ def helper():
         def paginate_users(users, page, per_page=10):
             start = (page - 1) * per_page
        -    end = start + per_page
        +    end = page + per_page
        +    query = "SELECT * FROM users WHERE name = '%s'" % users
             return users[start:end]
        """
    )
    prepared = prepare(diff, MAX_BYTES)
    contents = {e.path: reconstruct_new_file(e.text) for e in prepared.files}

    findings = static_analysis.analyse(contents, complete=())

    assert findings, "ruff found nothing in a line that is genuinely suspect"
    assert {f.line for f in findings} == {13}
    assert all(prepared.allows(f.file, f.line) for f in findings)
    assert "S608" in {f.code for f in findings}


def test_the_node_survives_a_diff_with_no_files():
    """Nothing to analyse is a skip with a reason, never "ok, 0 findings"."""
    result = static_analysis_node({"prepared": PreparedDiff(text="")})

    assert result["findings"] == []
    run = result["runs"][0]
    assert run.succeeded is False
    assert run.skipped_reason == "no Python or JS/TS files to analyse"
