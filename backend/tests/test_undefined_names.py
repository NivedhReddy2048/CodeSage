"""An undefined name in a whole file blocks, like a syntax error (issue #120).

DEV run 1: bugsinpy-pysnooper-3 writes to `output_path`, a name that does not exist,
so every call raises NameError. ruff said so (F821) and the review left it a nit,
because every lint rule but a syntax error was one.

The guard: a module with a star import or a module-level __getattr__ can supply
names ruff cannot see, so there the finding stays a nit.
"""

from pathlib import Path

import pytest

from apps.agents import policy, static_analysis
from apps.agents.diffs import prepare
from apps.agents.graph import Runtime
from apps.agents.nodes import static_analysis as static_analysis_node
from apps.agents.types import Category, Finding, Placement, ReviewConfig, Severity

CASE = Path(__file__).parents[2] / "eval" / "cases" / "dev" / "bugsinpy-pysnooper-3"

needs_ruff = pytest.mark.skipif(
    static_analysis.tool_command("ruff") is None, reason="ruff is not installed"
)

UNDEFINED = "def greet():\n    return message\n"


def ruff_findings(content, complete=True):
    report = static_analysis.run_analysis({"m.py": content}, complete={"m.py"} if complete else ())
    return [f for f in report.findings if f.tool == "ruff"]


@needs_ruff
def test_pysnooper_3_undefined_output_path_blocks():
    diff = (CASE / "diff.patch").read_text(encoding="utf-8")
    head = (CASE / "files" / "pysnooper" / "pysnooper.py").read_text(encoding="utf-8")
    state = {
        "prepared": prepare(diff, 60_000),
        "runtime": Runtime(ReviewConfig(), fetch_source=lambda path: head),
    }

    kept, dropped = policy.apply(static_analysis_node(state)["findings"])

    (finding,) = [f for f in kept if f.rule == "ruff F821"]
    assert (finding.file, finding.line) == ("pysnooper/pysnooper.py", 26)
    assert "output_path" in finding.message
    assert finding.severity == Severity.BLOCKING
    assert not finding.downgraded
    assert not dropped


@needs_ruff
def test_an_undefined_name_in_a_whole_file_is_blocking():
    (finding,) = ruff_findings(UNDEFINED)

    assert (finding.code, finding.line, finding.severity) == ("F821", 2, "blocking")


@needs_ruff
@pytest.mark.parametrize(
    "dynamic",
    [
        "from os.path import *\n",
        "try:\n    from os.path import *\nexcept ImportError:\n    pass\n",
        "def __getattr__(name):\n    return name\n",
    ],
    ids=["star import", "guarded star import", "module __getattr__"],
)
def test_a_module_that_can_define_names_dynamically_keeps_it_a_nit(dynamic):
    findings = ruff_findings(dynamic + "\n\n" + UNDEFINED)

    undefined = [f for f in findings if f.code in static_analysis.UNDEFINED_NAME_RULES | {"F405"}]
    assert undefined, "ruff should still report the name"
    assert {f.severity for f in findings} == {"nit"}


@needs_ruff
def test_a_method_named_getattr_is_not_the_module_hook():
    findings = ruff_findings(
        "class Proxy:\n    def __getattr__(self, name):\n        return name\n\n\n" + UNDEFINED
    )

    assert [(f.code, f.severity) for f in findings] == [("F821", "blocking")]


@needs_ruff
def test_on_a_reconstruction_from_hunks_it_is_still_suppressed():
    assert ruff_findings(UNDEFINED, complete=False) == []


def finding(rule, severity=Severity.BLOCKING):
    return Finding(
        file="m.py",
        line=2,
        severity=severity,
        category=Category.CORRECTNESS,
        message=f"{rule}: x",
        agent="static_analysis",
        rule=rule,
        placement=Placement.INLINE,
        anchored_by="tool",
    )


@pytest.mark.parametrize("rule", ["ruff F821", "ruff F822", "ruff F823", "ruff invalid-syntax"])
def test_policy_lets_blocking_lint_rules_block(rule):
    assert policy.cap(finding(rule)).severity == Severity.BLOCKING


@pytest.mark.parametrize("rule", ["ruff F841", "ruff F401", "ruff S608", "ruff B006"])
def test_every_other_lint_rule_is_still_a_nit(rule):
    capped = policy.cap(finding(rule))

    assert (capped.severity, capped.downgraded) == (Severity.NIT, "lint rule")
