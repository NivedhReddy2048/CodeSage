"""Inline review comments on the diff lines a finding points at.

The summary comment says what was found; an inline comment puts each finding next to
the code it is about, which is where a reviewer actually reads. Two rules:

1. **Never post the same comment twice.** A PR is reviewed on every push, and a
   rerun of the same commit must not stack a second copy of every comment. Each
   comment carries a hidden marker, and a finding is skipped when a live CodeSage
   comment already sits on the same file within synthesis' NEARBY_LINES of it - the
   same window synthesis uses to call two findings one defect, because a rerun
   routinely anchors the same defect a line or two away. GitHub nulls `line` on a comment
   whose code has since changed ("outdated"), so an outdated comment does not block
   a fresh one on the new code.

2. **Never fail the review over it.** The findings are already stored and summarised;
   a rejected inline comment costs that comment and nothing else.

The GitHub client is passed in rather than imported, so the caller's module (and the
tests that patch it) decide which client is used.
"""

import logging
from dataclasses import dataclass, field

from apps.agents.synthesis import NEARBY_LINES

logger = logging.getLogger(__name__)

MARKER = "<!-- codesage:inline -->"

SEVERITY_LABEL = {"blocking": "Blocking", "nit": "Nit"}


@dataclass
class InlineOutcome:
    posted: int = 0
    duplicates: int = 0
    failed: int = 0
    errors: list = field(default_factory=list)


def existing_locations(comments):
    """(path, line) of every live CodeSage inline comment already on the PR."""
    return {
        (comment.get("path"), comment.get("line"))
        for comment in comments
        if MARKER in (comment.get("body") or "") and comment.get("line")
    }


def already_covered(locations, path, line):
    """Is there a CodeSage comment on this file close enough to be the same defect?"""
    return any(p == path and abs(existing - line) <= NEARBY_LINES for p, existing in locations)


def render_comment(finding):
    label = SEVERITY_LABEL.get(finding.severity, finding.severity)
    category = f" · {finding.category}" if finding.category else ""
    return (
        f"**{label}{category}** — {finding.message}\n\n"
        f"<sub>CodeSage · {finding.agent.replace('_', ' ')}</sub>\n{MARKER}"
    )


def post_inline_comments(github, installation_id, pull_request, head_sha, findings, limit):
    """Post one inline comment per new finding location, deduplicated.

    `findings` are stored ReviewFinding rows, already ordered blocking-first by
    synthesis, so the cap keeps the most important ones.
    """
    outcome = InlineOutcome()
    if not findings or not head_sha:
        return outcome

    repo = pull_request.repository.full_name
    existing = existing_locations(
        github.list_review_comments(installation_id, repo, pull_request.number)
    )

    pending = []
    seen = set(existing)
    for finding in findings:
        key = (finding.file_path, finding.line)
        if already_covered(seen, *key):
            outcome.duplicates += 1
            continue
        seen.add(key)
        pending.append(
            {
                "path": finding.file_path,
                "line": finding.line,
                "side": "RIGHT",
                "body": render_comment(finding),
            }
        )
    pending = pending[:limit]
    if not pending:
        return outcome

    summary = (
        f"CodeSage left {len(pending)} inline comment{'s' if len(pending) != 1 else ''} "
        "on the changed lines. The full review is in the CodeSage comment above."
    )
    try:
        github.create_review(installation_id, repo, pull_request.number, head_sha, summary, pending)
        outcome.posted = len(pending)
        return outcome
    except Exception as exc:  # noqa: BLE001 - a GitHubAppError, or a transport failure
        # One bad anchor (usually a line GitHub does not consider part of the diff)
        # rejects the whole batch with a 422. Fall back to one at a time so the
        # rest still land.
        logger.warning("Batched inline review rejected, posting individually: %s", exc)

    for comment in pending:
        try:
            github.create_review_comment(
                installation_id, repo, pull_request.number, head_sha, comment
            )
            outcome.posted += 1
        except Exception as exc:  # noqa: BLE001
            outcome.failed += 1
            outcome.errors.append(f"{comment['path']}:{comment['line']}: {exc}"[:300])
            logger.warning(
                "Inline comment on %s:%s rejected: %s", comment["path"], comment["line"], exc
            )
    return outcome
