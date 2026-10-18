"""Merge findings from every agent into one review.

Deterministic, not a model call. Spec section 5 calls synthesis an agent, but
everything it has to do - deduplicate, rank, decide blocking versus nit - has a
correct answer. Asking a model would add latency, cost and a chance of
hallucination to a step that does not need one, and would spend budget better given
to the agents that actually read code.
"""

import logging

from apps.agents.types import Severity

logger = logging.getLogger(__name__)

# Which agent's wording to keep when two report the same defect. Static analysis
# first because a tool's message is precise and cites a rule id; security next
# because its framing of a shared finding is the one that matters.
AGENT_PRECEDENCE = ("static_analysis", "security", "grounding", "test_coverage", "review")

# Lines this close together are treated as the same defect. Two agents describing
# one bug rarely agree on the exact line - one points at the call, another at the
# assignment above it.
NEARBY_LINES = 2


def synthesise(findings, max_findings=25):
    """Deduplicate, order and cap. Blocking findings first, then nits."""
    if not findings:
        return []

    merged = _deduplicate(findings)
    merged.sort(key=_sort_key)
    return merged[:max_findings]


def _deduplicate(findings):
    """Collapse findings that describe the same defect.

    Grouped by file and approximate line rather than exact text, because the whole
    point of several agents is that they phrase the same problem differently.
    """
    groups = []

    for finding in sorted(findings, key=lambda f: (f.file, f.line)):
        placed = False
        for group in groups:
            head = group[0]
            if head.file == finding.file and abs(head.line - finding.line) <= NEARBY_LINES:
                group.append(finding)
                placed = True
                break
        if not placed:
            groups.append([finding])

    return [_pick(group) for group in groups]


def _pick(group):
    """Choose one finding to represent a group.

    Severity wins first: if any agent called it blocking, it is blocking - a
    disagreement about seriousness should resolve upward, since the cost of
    under-reporting a real defect is higher than the cost of an over-cautious flag.
    """
    if len(group) == 1:
        return group[0]

    blocking = [f for f in group if f.severity == Severity.BLOCKING]
    candidates = blocking or group

    chosen = min(candidates, key=lambda f: _precedence(f.agent))

    # Credit the other agents that saw it, so agreement is visible in the comment.
    others = sorted({f.agent for f in group} - {chosen.agent})
    if others:
        from dataclasses import replace

        chosen = replace(chosen, message=f"{chosen.message} (also flagged by {', '.join(others)})")
    return chosen


def _precedence(agent):
    try:
        return AGENT_PRECEDENCE.index(agent)
    except ValueError:
        return len(AGENT_PRECEDENCE)


def _sort_key(finding):
    return (
        0 if finding.severity == Severity.BLOCKING else 1,
        finding.file,
        finding.line,
    )
