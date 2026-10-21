"""Where a finding goes: an added line, existing code, or nowhere in particular.

A model's line number is a guess. Asked to count lines in a unified diff, the agents
were off by one or two on every testbed PR - :4 and :15 for changes on :3 and :17-18
(PR #7), :11 for a `finally:` on :12 (PR #6) - and those guesses landed on blank
and unchanged lines that the diff check accepted. So the agents now quote the line
they mean in `evidence`, and the anchor is wherever that text actually is.

The rules, in order:

1. Evidence found on an added line: anchor there (nearest the cited line if the text
   appears more than once). It is inline.
2. Evidence found only on unchanged lines: the finding is about existing code. It is
   listed in the summary and never posted inline, because the author did not write
   that line.
3. No evidence, or evidence that matches nothing: trust the cited line if it is an
   added line; otherwise snap to the nearest added line within SNAP_WINDOW in the
   same hunk; otherwise the finding is "general" - summarised, never inline.

Findings about a file that is not in the diff are dropped, as before.
"""

import re
from dataclasses import replace

from apps.agents.diffs import diff_lines
from apps.agents.types import Placement

# How far a finding without usable evidence may be moved to reach an added line.
SNAP_WINDOW = 3
# Evidence shorter than this must equal a whole line; longer may be a fragment of
# one. A short fragment ("return 0", "x") matches too many lines to mean anything.
MIN_FRAGMENT = 8

# A quote copied from the numbered diff, with the number and marker still on it:
# "  17 + |     if not orders:". The pipe makes the prefix unambiguous.
NUMBERED_PREFIX = re.compile(r"^\s*\d*\s*[+\- ]?\s*\|\s?")
# A quote copied from a raw unified diff: "+    if not orders:".
DIFF_MARKER = re.compile(r"^[+\-](?=\s)")


def normalise(text):
    """Whitespace-insensitive form of one line of code."""
    text = NUMBERED_PREFIX.sub("", text, count=1)
    text = DIFF_MARKER.sub("", text, count=1)
    return " ".join(text.split())


def evidence_lines(evidence):
    """The quoted lines, normalised, without blanks or elisions."""
    quoted = [normalise(line) for line in (evidence or "").splitlines()]
    return [line for line in quoted if line and line not in {"...", "…"}]


def new_file_lines(entry):
    """`{number: DiffLine}` for every line of the new file the diff shows."""
    return {line.number: line for line in diff_lines(entry.text) if line.number is not None}


def matching_lines(evidence, lines):
    """New-file line numbers whose text is the quoted evidence.

    Per quoted line, an exact (normalised) match beats a fragment match, so a quote
    of a whole line is not also matched against every longer line containing it.
    """
    found = set()
    for quote in evidence_lines(evidence):
        exact = {n for n, line in lines.items() if normalise(line.text) == quote}
        if exact:
            found |= exact
        elif len(quote) >= MIN_FRAGMENT:
            found |= {n for n, line in lines.items() if quote in normalise(line.text)}
    return found


def _nearest(numbers, cited):
    return min(numbers, key=lambda n: (abs(n - cited), n))


def anchor(finding, prepared):
    """The finding with its line and placement decided, or None to drop it."""
    entry = prepared.entry(finding.file)
    if entry is None:
        return None

    lines = new_file_lines(entry)
    matches = matching_lines(finding.evidence, lines)
    added = {n for n in matches if lines[n].kind == "+"}

    if added:
        return replace(
            finding,
            line=_nearest(added, finding.line),
            placement=Placement.INLINE,
            anchored_by="evidence",
        )
    if matches:
        return replace(
            finding,
            line=_nearest(matches, finding.line),
            placement=Placement.EXISTING,
            anchored_by="evidence",
        )

    cited = lines.get(finding.line)
    if cited is not None and cited.kind == "+":
        return replace(finding, placement=Placement.INLINE, anchored_by="cited")
    if cited is not None:
        nearby = {
            n
            for n, line in lines.items()
            if line.kind == "+" and line.hunk == cited.hunk and abs(n - finding.line) <= SNAP_WINDOW
        }
        if nearby:
            return replace(
                finding,
                line=_nearest(nearby, finding.line),
                placement=Placement.INLINE,
                anchored_by="snapped",
            )
    return replace(finding, placement=Placement.GENERAL, anchored_by="")


def anchor_all(findings, prepared):
    anchored = (anchor(finding, prepared) for finding in findings)
    return [finding for finding in anchored if finding is not None]
