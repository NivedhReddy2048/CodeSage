"""Merge findings from every agent into one review, and record what became of each.

Deterministic, not a model call. Spec section 5 calls synthesis an agent, but
everything it has to do - deduplicate, rank, cap - has a correct answer. Asking a
model would add latency, cost and a chance of hallucination to a step that does not
need one. Severity is no longer decided here: `policy` sets it on the raw findings
first, so a merge can only carry a severity some member already justified.

WHEN TWO FINDINGS ARE ONE
Only when they sit on the same anchored line AND describe the same issue: the same
tool rule id, or the same category with clearly overlapping wording. Proximity alone
never merges. It used to (within two lines), and on testbed PR #5 that folded four
raw findings into one - a distinct security finding about db_path vanished, and an
unrelated lint artefact was credited as "also flagged by static_analysis".

Findings from one agent are never merged with each other: an agent that lists two
things on a line means two things. The only exception is a verbatim repeat.

THE REPRESENTATIVE
The member whose evidence matched an added line and whose wording is definite, then
the most severe, then by agent precedence. A security agent's explanation reads
better than a linter's one-liner, so it leads; the linter's rule id is still named in
"(also flagged by static_analysis: bandit B608)".
"""

import logging
import re
from dataclasses import replace

from apps.agents.policy import SPECULATIVE
from apps.agents.types import Severity, TraceEntry

logger = logging.getLogger(__name__)

# Which agent's wording leads when several report one defect, after evidence and
# certainty. Security first because its framing of a shared finding is the one that
# matters; static analysis keeps its rule id in the credit line either way.
AGENT_PRECEDENCE = ("security", "grounding", "static_analysis", "test_coverage", "review")

# Two messages describe the same issue when this share of the shorter message's
# content words appear in the other, and at least MIN_SHARED_WORDS do.
SIMILARITY = 0.35
MIN_SHARED_WORDS = 2

_WORD = re.compile(r"[a-z0-9_]{3,}")
_STOPWORDS = frozenset(
    "the and for with that this from into are was were has have not but can will its "
    "when then than any all via may might could would should which while where there "
    "here your their been being does did also only just more most such what".split()
)


def synthesise(findings, max_findings=25):
    """Deduplicate, order and cap. Blocking findings first, then nits."""
    return synthesise_traced(findings, max_findings)[0]


def synthesise_traced(findings, max_findings=25):
    """`(final, trace)`: the final findings, and a TraceEntry for every input."""
    if not findings:
        return [], []

    groups = _group(findings)
    representatives = [(_merge(group), group) for group in groups]
    representatives.sort(key=lambda pair: _sort_key(pair[0]))

    final = []
    trace = [None] * len(findings)
    for merged, group in representatives:
        index = len(final) if len(final) < max_findings else None
        if index is not None:
            final.append(merged)
        lead = group[0]
        for position, member in group:
            if index is None:
                trace[position] = TraceEntry(member, "dropped", "over the findings limit")
            elif (position, member) == lead:
                trace[position] = TraceEntry(member, "kept", final_index=index)
            else:
                trace[position] = TraceEntry(
                    member,
                    "merged",
                    f"merged into {lead[1].agent}'s finding: same line, same issue",
                    final_index=index,
                )
    return final, trace


def _group(findings):
    """Groups of `(position, finding)`, the representative first in each."""
    groups = []
    for position, finding in enumerate(findings):
        for group in groups:
            if all(_same_issue(finding, member) for _, member in group):
                group.append((position, finding))
                break
        else:
            groups.append([(position, finding)])
    return [sorted(group, key=lambda pair: _rank(pair[1])) for group in groups]


def _same_issue(a, b):
    if (a.file, a.line, a.placement) != (b.file, b.line, b.placement):
        return False
    if a.agent == b.agent:
        return _normalised(a.message) == _normalised(b.message)
    if a.rule and b.rule:
        return a.rule == b.rule
    if a.category != b.category:
        return False
    return similar(a.message, b.message)


def similar(a, b):
    """Do two messages describe the same issue? Overlap of their content words."""
    words_a, words_b = _content_words(a), _content_words(b)
    if not words_a or not words_b:
        return False
    shared = words_a & words_b
    return (
        len(shared) >= MIN_SHARED_WORDS
        and len(shared) / min(len(words_a), len(words_b)) >= SIMILARITY
    )


def _content_words(message):
    # A tool's "(ruff F401)" or "bandit B608:" names the rule, not the defect.
    text = re.sub(r"\b(?:ruff|bandit|pattern-scan)\s+\S+", " ", message.lower())
    return {_stem(word) for word in _WORD.findall(text) if word not in _STOPWORDS}


def _stem(word):
    for suffix in ("ation", "ions", "ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _normalised(message):
    return " ".join(message.lower().split())


def _rank(finding):
    """Best representative first: evidenced, definite, severe, then by agent."""
    evidenced = finding.anchored_by in {"evidence", "tool"}
    definite = finding.agent == "static_analysis" or not SPECULATIVE.search(finding.message)
    return (
        not evidenced,
        not definite,
        finding.severity != Severity.BLOCKING,
        _precedence(finding.agent),
    )


def _merge(group):
    lead = group[0][1]
    members = [finding for _, finding in group]
    if any(f.severity == Severity.BLOCKING for f in members):
        lead = replace(lead, severity=Severity.BLOCKING, downgraded="")

    credits = []
    for finding in members[1:]:
        if finding.agent == lead.agent:
            continue  # a verbatim repeat, not a second opinion
        credit = finding.agent + (f": {finding.rule}" if finding.rule else "")
        if credit not in credits:
            credits.append(credit)
    if credits:
        lead = replace(lead, message=f"{lead.message} (also flagged by {', '.join(credits)})")
    return lead


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
