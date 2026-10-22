"""When does a finding count as catching a ground-truth bug?

Every number in the evaluation rests on this one function, so it is small, explicit
and tested on its own.

HEADLINE: the same file, a line within +-2 of the bug's line range, and a finding
category the frozen equivalence map (eval/categories.json) accepts for the bug's
category. The finding must be anchored to a line - an "inline" or "existing code"
placement. A "general" finding shows no line to the reader, so its model-cited
number cannot be credited with pointing at the bug.

LENIENT: the same file, +-3 lines, any category, any placement. Reported beside the
headline so the cost of the strict rule is visible rather than hidden.

ONE-TO-ONE (amendment H1, after DEV run 1). Within a run, a finding credits at most
one bug: `assign` pairs findings with bugs by a maximum matching. On testbed-pr1 a
single finding sat within two lines of two bugs one line apart and was credited for
both.
"""

import json
from dataclasses import dataclass
from pathlib import Path

HEADLINE_TOLERANCE = 2
LENIENT_TOLERANCE = 3
ANCHORED_PLACEMENTS = frozenset({"inline", "existing"})


@dataclass(frozen=True)
class Rule:
    name: str
    tolerance: int
    check_category: bool
    require_anchor: bool


HEADLINE = Rule("headline", HEADLINE_TOLERANCE, check_category=True, require_anchor=True)
LENIENT = Rule("lenient", LENIENT_TOLERANCE, check_category=False, require_anchor=False)


def load_categories(path):
    """The equivalence map: bug category -> finding categories that describe it."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {key: frozenset(values) for key, values in data["equivalent"].items()}


def matches(finding, bug, rule, categories):
    """Does `finding` (a dict) catch `bug` (a dict) under `rule`?

    finding: {"file", "line", "category", "placement"}
    bug:     {"file", "lines": [start, end], "category"}
    """
    if finding.get("file") != bug["file"]:
        return False
    if rule.require_anchor and finding.get("placement", "inline") not in ANCHORED_PLACEMENTS:
        return False
    start, end = bug["lines"]
    line = int(finding.get("line") or 0)
    if not start - rule.tolerance <= line <= end + rule.tolerance:
        return False
    if rule.check_category:
        accepted = categories.get(bug["category"], frozenset({bug["category"]}))
        return finding.get("category") in accepted
    return True


def caught(findings, bug, rule, categories):
    """The findings that catch `bug`."""
    return [f for f in findings if matches(f, bug, rule, categories)]


def distance(finding, bug):
    """Lines between a finding and a bug's range; 0 inside it."""
    start, end = bug["lines"]
    line = int(finding.get("line") or 0)
    return max(0, start - line, line - end)


def assign(findings, bugs, rule, categories):
    """`{bug id: finding}`: each finding credits at most one bug (H1).

    The most bugs that can be caught at once, and among those assignments the one
    with its findings closest to the bugs, so a finding goes to the bug it is on
    rather than the neighbour it also happens to be near. Exhaustive: a case has a
    handful of bugs and each has only the few findings within a few lines.
    """
    candidates = [
        sorted(
            (distance(f, bug), index)
            for index, f in enumerate(findings)
            if matches(f, bug, rule, categories)
        )
        for bug in bugs
    ]
    best = (0, 0, {})  # (bugs caught, -total distance, assignment)

    def search(position, used, caught_count, total, chosen):
        nonlocal best
        if position == len(bugs):
            if (caught_count, -total) > best[:2]:
                best = (caught_count, -total, dict(chosen))
            return
        if caught_count + (len(bugs) - position) < best[0]:
            return  # cannot beat what is already found
        for gap, index in candidates[position]:
            if index not in used:
                chosen[bugs[position]["id"]] = index
                search(position + 1, used | {index}, caught_count + 1, total + gap, chosen)
                del chosen[bugs[position]["id"]]
        search(position + 1, used, caught_count, total, chosen)

    search(0, frozenset(), 0, 0, {})
    return {bug_id: findings[index] for bug_id, index in best[2].items()}


def on_the_line(finding, bug):
    """Anchoring accuracy: is the finding inline, exactly within the bug's range?"""
    start, end = bug["lines"]
    return (
        finding.get("placement") == "inline"
        and finding.get("file") == bug["file"]
        and start <= int(finding.get("line") or 0) <= end
    )
