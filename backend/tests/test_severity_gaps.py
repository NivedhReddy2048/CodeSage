"""Severity gaps left by #90: a file that does not parse, and JS that runs strings.

#90 made every lint rule a nit and let only bandit block. That filed testbed PR #8's
first commit (f701890) - app/money.py with every line indented by three spaces,
so the file does not parse - as a nit (review 45), and made eval() a nit too.

These run the real linters and pattern scan through the pipeline; only the LLM
agents are mocked.
"""

import json
from pathlib import Path
from unittest import mock

import pytest

from apps.agents import policy, static_analysis
from apps.agents.graph import Runtime, run_pipeline
from apps.agents.nodes import uniform_indent
from apps.agents.providers import ProviderResponse
from apps.agents.types import Category, Finding, Placement, RepoContext, ReviewConfig, Severity

FIXTURES = Path(__file__).parent / "fixtures" / "testbed"

needs_ruff = pytest.mark.skipif(
    static_analysis.tool_command("ruff") is None, reason="ruff is not installed"
)


def review(diff, security=()):
    def complete(self, model, system_prompt, user_message, schema=None):
        if "classify" in system_prompt:
            body = '{"intent": "feature", "summary": "s"}'
        elif "security reviewer" in system_prompt:
            body = json.dumps({"findings": list(security)})
        else:
            body = '{"findings": []}'
        return ProviderResponse(body, 10, 5), "groq", False

    config = ReviewConfig(groq_api_key="k", gemini_api_key="k", backoff_seconds=0, max_retries=1)
    with mock.patch.object(Runtime, "complete", complete):
        return run_pipeline(diff, RepoContext("o/testbed", 8, "t"), config)


def new_file(path, *lines):
    body = "".join(f"+{line}\n" for line in lines)
    return (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n{body}"
    )


# ------------------------------------------------------------ syntax errors


@needs_ruff
def test_pr8_f701890_a_file_that_does_not_parse_blocks():
    """The real first commit of testbed PR #8: all of money.py indented by 3 spaces."""
    result = review((FIXTURES / "pr8_f701890.diff.txt").read_text(encoding="utf-8"))

    (found,) = [f for f in result.findings if f.agent == "static_analysis"]
    assert (found.file, found.line, found.severity) == ("app/money.py", 1, Severity.BLOCKING)
    assert found.rule == "ruff invalid-syntax"
    assert found.message == (
        "ruff invalid-syntax: Unexpected indentation (the whole file is indented by 3 spaces)"
    )
    # The tool's exact line is the evidence, and it is a line the PR added.
    assert found.evidence == '   """Money helpers that avoid floating-point rounding errors."""'
    assert (found.placement, found.anchored_by, found.downgraded) == (
        Placement.INLINE,
        "tool",
        "",
    )


@needs_ruff
def test_a_syntax_error_in_an_otherwise_normal_new_file_blocks_without_the_indent_note():
    result = review(new_file("app/x.py", "def broken(:", "    return 1"))

    syntax = [f for f in result.findings if f.agent == "static_analysis"]
    assert syntax and all(f.severity == Severity.BLOCKING for f in syntax)
    assert not any("indented by" in f.message for f in syntax)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('   """Doc."""\n\n   from x import y\n   def f():\n       return 1\n', "3 spaces"),
        ("\tx = 1\n\ty = 2\n", "1 tab"),
        ("x = 1\n    y = 2\n", ""),
        # Every line shares two spaces; one has a third.
        ("  x = 1\n   y = 2\n", "2 spaces"),
        ("", ""),
    ],
)
def test_uniform_indent(content, expected):
    assert uniform_indent(content) == expected


@pytest.mark.parametrize(
    ("rule", "severity"),
    [
        ("ruff invalid-syntax", Severity.BLOCKING),
        ("ruff E999", Severity.BLOCKING),
        ("ruff F401", Severity.NIT),
        ("ruff S608", Severity.NIT),
        ("bandit B608", Severity.BLOCKING),
        ("pattern-scan js-eval", Severity.BLOCKING),
        ("pattern-scan js-new-function", Severity.BLOCKING),
        ("pattern-scan js-inner-html", Severity.NIT),
    ],
)
def test_which_tool_rules_may_block(rule, severity):
    finding = Finding(
        file="a",
        line=1,
        severity=Severity.BLOCKING,
        category=Category.SECURITY,
        message="m",
        agent="static_analysis",
        placement=Placement.INLINE,
        anchored_by="tool",
        rule=rule,
    )
    assert policy.cap(finding).severity == severity


# ------------------------------------------------------------- JS pattern scan

SINK = "  el.innerHTML = params.get('q');"


@pytest.mark.parametrize(
    ("line", "rule"),
    [
        ("  return eval(input);", "pattern-scan js-eval"),
        ("  const f = new Function(src);", "pattern-scan js-new-function"),
    ],
)
def test_eval_and_new_function_on_an_added_line_block(line, rule):
    result = review(new_file("web/run.js", "export function run(input, src) {", line, "}"))

    (found,) = result.findings
    assert (found.rule, found.severity, found.line) == (rule, Severity.BLOCKING, 2)


@pytest.mark.parametrize(
    "line",
    [SINK, "  return <div dangerouslySetInnerHTML={{ __html: html }} />;"],
)
def test_an_inner_html_sink_alone_is_a_nit(line):
    result = review(new_file("web/view.jsx", "export function show(el, html) {", line, "}"))

    (found,) = result.findings
    assert found.severity == Severity.NIT


def test_an_inner_html_sink_the_security_agent_flags_merges_as_blocking():
    message = (
        "The q query parameter is assigned straight to innerHTML, so a crafted URL "
        "injects script into the page (XSS). Use textContent."
    )
    result = review(
        new_file("web/view.js", "export function show(el, params) {", SINK, "}"),
        security=[
            {
                "file": "web/view.js",
                "line": 2,
                "severity": "blocking",
                "category": "security",
                "message": message,
                "evidence": SINK.strip(),
            }
        ],
    )

    (found,) = result.findings
    assert found.severity == Severity.BLOCKING
    assert found.agent == "security"
    assert (
        found.message == f"{message} (also flagged by static_analysis: pattern-scan js-inner-html)"
    )
    assert sorted(t.outcome for t in result.trace) == ["kept", "merged"]
