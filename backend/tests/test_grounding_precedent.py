"""Grounding never treats an existing defect as precedent (issue #122).

DEV run 1, testbed-pr5: the PR replaces an f-string SQL query with a parameterised
one. Grounding retrieved the testbed's own `OrderRepository.search_by_status`, which
still builds SQL from an f-string, and reported the fix as "inconsistent with the
established pattern: existing queries use f-strings" - advice to put the injection
back.

What the model does with the rule cannot be checked offline, so there are two tests:
the rule is in the prompt (always), and the testbed-pr5 situation against the real
model (opt-in: CODESAGE_LIVE_TESTS=1 and a Groq key; spends ~3K gpt-oss-20b tokens
per repeat).
"""

import json
import os
import re
from dataclasses import replace
from pathlib import Path

import pytest

from apps.agents import agent_prompts, policy
from apps.agents.diffs import prepare
from apps.agents.graph import Runtime
from apps.agents.nodes import grounding
from apps.agents.types import (
    Category,
    Finding,
    Placement,
    RepoContext,
    RetrievedChunk,
    Severity,
)

CASE = Path(__file__).parents[2] / "eval" / "cases" / "dev" / "testbed-pr5"

# What retrieval really returned for this PR from the testbed index at a6ddd12. It
# includes OrderRepository.search_by_status, the defect that was cited as precedent.
RETRIEVED = [
    RetrievedChunk(**chunk)
    for chunk in json.loads(
        (Path(__file__).parent / "fixtures" / "testbed" / "pr5_retrieved.json").read_text(
            encoding="utf-8"
        )
    )["chunks"]
]

# A finding on the fixed lines that calls the change inconsistent with the old way.
ENDORSES_THE_DEFECT = re.compile(
    r"inconsisten|established pattern|f-string|interpolat|string format", re.IGNORECASE
)

# What gpt-oss-20b said on testbed-pr5: in DEV run 1, and live with the rule in the
# prompt while this was written.
SEEN = [
    "Inconsistent with established pattern: existing queries use f-strings for string "
    "interpolation, but this change uses a parameterized query. (see app/orders.py:6-36)",
    "Inconsistent query construction pattern: uses parameterized query while existing code "
    "uses f-strings. (see app/orders.py:6-36)",
    "Uses parameterized query while existing code uses f-strings for queries, inconsistent "
    "with established pattern. (see app/orders.py:6-36)",
]


FIXED_QUERY = 'query = "SELECT * FROM orders WHERE customer = ?"'


def grounding_finding(message, evidence=FIXED_QUERY, line=9):
    return Finding(
        file="app/reports.py",
        line=line,
        severity=Severity.NIT,
        category=Category.CORRECTNESS,
        message=message,
        agent="grounding",
        evidence=evidence,
        placement=Placement.INLINE,
        anchored_by="evidence",
    )


def test_the_prompt_says_a_defect_is_not_precedent():
    prompt = agent_prompts.GROUNDING_SYSTEM_PROMPT

    assert "PRECEDENT ONLY WHEN IT IS NOT ITSELF A DEFECT" in prompt
    assert "safer or more correct than the existing code" in prompt
    assert "parameterised query" in prompt
    # Stated with the task, before the citation rules and the output contract.
    assert prompt.index("NOT ITSELF A DEFECT") < prompt.index("CITATIONS ARE MANDATORY")


def test_the_pr5_message_shows_the_defect_and_the_fix_side_by_side():
    prepared = prepare((CASE / "diff.patch").read_text(encoding="utf-8"), 60_000)

    message = agent_prompts.build_grounding_message(prepared, RETRIEVED, "fix: parameterise")

    assert "app/orders.py:17-20 [OrderRepository.search_by_status]" in message
    assert '    9 + |     query = "SELECT * FROM orders WHERE customer = ?"' in message


@pytest.mark.parametrize("message", SEEN)
@pytest.mark.parametrize(
    ("line", "evidence"), [(9, FIXED_QUERY), (10, "cursor.execute(query, (customer_name,))")]
)
def test_policy_drops_grounding_faulting_the_pr5_fix(message, line, evidence):
    kept, dropped = policy.apply([grounding_finding(message, evidence, line)])

    assert kept == []
    ((_, reason),) = dropped
    assert reason == "out of scope: grounding faulting a change for being safer than existing code"


@pytest.mark.parametrize(
    ("message", "evidence"),
    [
        (
            "Does not follow the existing pattern: the connection is opened with a context "
            "manager here but closed by hand everywhere else.",
            "with sqlite3.connect(path) as conn:",
        ),
        (
            "Unlike the existing renderers, this escapes the name before inserting it.",
            'html = "<b>" + html.escape(name) + "</b>"',
        ),
    ],
)
def test_the_same_rule_holds_for_other_safer_constructs(message, evidence):
    assert policy.faults_a_safer_change(grounding_finding(message, evidence))


@pytest.mark.parametrize(
    ("message", "evidence"),
    [
        # The change is the less safe side: real findings that name the same constructs.
        (
            "Inconsistent with the parameterized queries elsewhere: this builds the query "
            "with an f-string.",
            "query = f\"SELECT * FROM orders WHERE status = '{status}'\"",
        ),
        (
            "Unlike existing code, which uses a context manager, this does not close the "
            "connection.",
            "conn = sqlite3.connect(path)",
        ),
        (
            "Inconsistent with the existing pattern of bound parameters.",
            'cursor.execute(f"SELECT * FROM t WHERE a = {a}", ())',
        ),
        # Duplication is grounding's job, validation included.
        ("lookup_user reimplements UserRepository.find_by_id (see app/users.py:6-37)", "x"),
        (
            "Reimplements the email check in `is_valid_email`; inconsistent with the existing "
            "validation helper. (see app/users.py:1-9)",
            'if "@" not in email:',
        ),
        # Naming the safe construct without calling the change inconsistent.
        (
            "Duplicates the parameterized lookup already in `OrderRepository.find_by_id`.",
            FIXED_QUERY,
        ),
    ],
)
def test_ordinary_grounding_findings_are_kept(message, evidence):
    kept, dropped = policy.apply([grounding_finding(message, evidence)])

    assert [f.message for f in kept] == [message]
    assert dropped == []


def test_without_a_quoted_added_line_the_finding_is_kept():
    finding = replace(grounding_finding(SEEN[0]), anchored_by="snap")

    assert policy.out_of_scope(finding) == ""


def test_other_agents_are_not_held_to_the_grounding_rule():
    finding = replace(grounding_finding(SEEN[0]), agent="correctness")

    assert policy.out_of_scope(finding) == ""


live = pytest.mark.skipif(
    os.environ.get("CODESAGE_LIVE_TESTS") != "1",
    reason="live model test; set CODESAGE_LIVE_TESTS=1",
)


@live
def test_live_grounding_does_not_ask_the_pr5_fix_to_revert(capsys):
    """Through the real model and the policy. Prints how often the model alone erred."""
    from apps.reviews.services import build_config

    config = replace(build_config(), gemini_api_key="")
    if not config.groq_api_key:
        pytest.skip("no Groq key")
    prepared = prepare((CASE / "diff.patch").read_text(encoding="utf-8"), config.max_diff_bytes)
    repeats = int(os.environ.get("CODESAGE_LIVE_REPEATS", "3"))

    model_erred = 0
    for _ in range(repeats):
        state = {
            "runtime": Runtime(config, retrieve=lambda query: list(RETRIEVED)),
            "prepared": prepared,
            "context": RepoContext("NivedhReddy2048/codesage-testbed", 5, "Fix SQL injection"),
            "intent": "",
        }
        out = grounding(state)
        assert out["runs"][0].succeeded, out["runs"][0].error

        def endorsing(findings):
            return [
                f for f in findings if f.line in (9, 10) and ENDORSES_THE_DEFECT.search(f.message)
            ]

        model_erred += bool(endorsing(out["findings"]))
        kept, _ = policy.apply(out["findings"])
        assert not endorsing(kept), [f.message for f in endorsing(kept)]

    with capsys.disabled():
        print(f"\nmodel faulted the fix in {model_erred}/{repeats} runs; policy kept none")
