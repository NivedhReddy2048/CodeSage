"""Citation enforcement for the grounding agent (spec section 6).

A grounded finding is only worth more than an ungrounded one if the citation is
real. A model asked to cite its sources will produce citations whether or not it
used them: plausible file paths, plausible line numbers, occasionally a file it was
never shown. Posted on a PR those look authoritative and are wrong, which is worse
than no citation at all.

So the rule is checked rather than requested: a finding survives only if its cited
location falls inside a chunk that was actually in the retrieved set for that query.
"""

import logging

logger = logging.getLogger(__name__)


def find_supporting_chunk(retrieved, file_path, line):
    """The retrieved chunk covering this location, or None."""
    if not file_path or not line:
        return None
    for chunk in retrieved:
        if chunk.covers(file_path, line):
            return chunk
    return None


def format_citation(chunk):
    """`app/users.py:15-20` - what a reader can click through to."""
    return f"{chunk.file_path}:{chunk.line_start}-{chunk.line_end}"


def validate(findings, retrieved):
    """Keep only findings whose citation points into the retrieved set.

    Returns `(kept, dropped)` so the caller can report how many were discarded;
    silently dropping would hide a model that cites badly every time.
    """
    kept = []
    dropped = []

    for finding, cited_file, cited_line in findings:
        chunk = find_supporting_chunk(retrieved, cited_file, cited_line)
        if chunk is None:
            logger.info(
                "Dropping ungrounded finding: cited %s:%s which was not retrieved",
                cited_file,
                cited_line,
            )
            dropped.append(finding)
            continue
        kept.append((finding, format_citation(chunk)))

    return kept, dropped
