"""Inline review comments on the diff lines a finding points at.

The summary comment says what was found; an inline comment puts each finding next to
the code it is about, which is where a reviewer actually reads. Two rules:

1. **Only on a line the PR added.** Findings anchored to existing code or to no
   line at all ("general") are summarised, never posted inline, and an inline
   comment sits on exactly the line the summary names.

2. **Never post the same comment twice.** A PR is reviewed on every push, and a
   rerun of the same commit must not stack a second copy of every comment. Each
   comment carries a hidden marker, and a finding is skipped when a live CodeSage
   comment already sits on the same file and line. Anchors come from the quoted
   evidence rather than a model's count, so a rerun lands on the same line. GitHub
   nulls `line` on a comment whose code has since changed ("outdated"), so an
   outdated comment does not block a fresh one on the new code.

3. **Never leave a stale verdict standing.** A comment whose finding is gone, or whose
   severity changed, is edited to say "Superseded by review of <sha>" with the old
   text struck through, and its thread is resolved where GitHub allows. Comments are
   never deleted: the history of what was said stays readable.

4. **Never fail the review over it.** The findings are already stored and summarised;
   a rejected inline comment costs that comment and nothing else.

The GitHub client is passed in rather than imported, so the caller's module (and the
tests that patch it) decide which client is used.
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MARKER = "<!-- codesage:inline -->"
SUPERSEDED_MARKER = "<!-- codesage:superseded -->"
_LABEL = re.compile(r"^\*\*(Blocking|Nit)\b")

SEVERITY_LABEL = {"blocking": "Blocking", "nit": "Nit"}


@dataclass
class InlineOutcome:
    posted: int = 0
    duplicates: int = 0
    failed: int = 0
    # Earlier comments edited to "Superseded by review of ...", and how many of
    # their threads GitHub let us resolve.
    superseded: int = 0
    resolved: int = 0
    errors: list = field(default_factory=list)


def is_ours(comment):
    return MARKER in (comment.get("body") or "")


def is_superseded(comment):
    return SUPERSEDED_MARKER in (comment.get("body") or "")


def comment_severity(body):
    """ "blocking" or "nit", read back from the label render_comment wrote."""
    match = _LABEL.match((body or "").lstrip())
    return match.group(1).lower() if match else ""


def superseded_body(body, head_sha):
    """The old comment, struck through line by line, under a notice. Nothing is lost."""
    original = (body or "").replace(MARKER, "").rstrip()
    struck = "\n".join(
        f"~~{line}~~" if line.strip() and not line.lstrip().startswith("<") else line
        for line in original.splitlines()
    )
    return (
        f"Superseded by review of `{(head_sha or '')[:7]}`.\n\n{struck}\n"
        f"{SUPERSEDED_MARKER}\n{MARKER}"
    )


def _current_keys(findings):
    return {
        (f.file_path, f.line, str(f.severity))
        for f in findings
        if getattr(f, "placement", "inline") not in {"existing", "general"}
    }


def supersede_stale(github, installation_id, pull_request, head_sha, findings, comments, outcome):
    """Mark earlier CodeSage comments whose verdict no longer stands. Returns those that do.

    Still standing: a live comment on a line where this review has an inline finding
    of the same severity. Anything else - the finding is gone, its severity changed,
    or GitHub marked the comment outdated (`line` is null) - is superseded.
    """
    repo = pull_request.repository.full_name
    current = _current_keys(findings)
    standing, stale = [], []
    for comment in comments:
        if not is_ours(comment) or is_superseded(comment):
            continue
        key = (comment.get("path"), comment.get("line"), comment_severity(comment.get("body")))
        if comment.get("line") and key in current:
            standing.append(comment)
        else:
            stale.append(comment)

    edited = []
    for comment in stale:
        try:
            github.update_review_comment(
                installation_id, repo, comment["id"], superseded_body(comment["body"], head_sha)
            )
        except Exception as exc:  # noqa: BLE001 - a stale label costs clarity, not the review
            logger.warning("Could not mark comment %s superseded: %s", comment.get("id"), exc)
            outcome.errors.append(f"supersede {comment.get('id')}: {exc}"[:300])
            continue
        outcome.superseded += 1
        edited.append(comment["id"])

    if edited:
        _resolve_threads(github, installation_id, pull_request, edited, outcome)
    return standing


def _resolve_threads(github, installation_id, pull_request, comment_ids, outcome):
    """Resolve each superseded comment's thread; stop at the first refusal.

    A refusal is almost always a permission the App lacks, and it would refuse the rest
    the same way. The edit has already said everything that matters.
    """
    repo = pull_request.repository.full_name
    try:
        threads = github.list_review_threads(installation_id, repo, pull_request.number)
    except Exception as exc:  # noqa: BLE001
        logger.info("Not resolving superseded threads: %s", exc)
        return
    for comment_id in comment_ids:
        thread_id, resolved = threads.get(comment_id, (None, False))
        if not thread_id or resolved:
            continue
        try:
            github.resolve_review_thread(installation_id, thread_id)
        except Exception as exc:  # noqa: BLE001
            # Seen live: FORBIDDEN "Resource not accessible by integration" with
            # pull_requests: write. Said once per review, then edits alone carry it.
            logger.warning("GitHub refused to resolve superseded threads: %s", exc)
            return
        outcome.resolved += 1


def existing_locations(comments):
    """(path, line) of every live CodeSage inline comment already on the PR."""
    return {
        (comment.get("path"), comment.get("line"))
        for comment in comments
        if MARKER in (comment.get("body") or "") and comment.get("line")
    }


def already_covered(locations, path, line):
    """Is there already a CodeSage comment on this exact line?"""
    return (path, line) in locations


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
    if not head_sha:
        return outcome

    repo = pull_request.repository.full_name
    comments = github.list_review_comments(installation_id, repo, pull_request.number)
    # Before posting: a comment whose verdict changed must not count as "already
    # said", or the corrected finding would never be posted beside it.
    standing = supersede_stale(
        github, installation_id, pull_request, head_sha, findings, comments, outcome
    )
    existing = existing_locations(standing)

    pending = []
    seen = set(existing)
    for finding in findings:
        if getattr(finding, "placement", "inline") in {"existing", "general"}:
            continue
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
