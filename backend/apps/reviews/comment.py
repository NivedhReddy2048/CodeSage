"""Render the review as the body of the bot's PR comment.

Two constraints shape this:

1. **It must change on every run.** Phase 2's verification showed GitHub no-ops a
   PATCH whose body is byte-identical and does not move `updated_at`, so a constant
   body makes a re-review invisible. Including the reviewed head SHA guarantees every
   `synchronize` is a real edit.

2. **It must disclose what it did not look at.** A short review of a truncated diff
   looks identical to a short review of clean code unless it says otherwise.
"""

from apps.reviews.pricing import format_footer

SEVERITY_LABEL = {"blocking": "Blocking", "nit": "Nit"}

HEADER = "## CodeSage review"

ACK_BODY = (
    "**CodeSage is reviewing this PR...**\n\n"
    "A multi-agent review is running. This comment will be updated with the findings "
    "when it completes."
)


def render_running(head_sha):
    """Shown while a review is in flight, naming the commit being reviewed."""
    return (
        f"{HEADER}\n\n"
        f"Reviewing `{_short(head_sha)}`...\n\n"
        "This comment will be updated with the findings when the review completes."
    )


def render(review, findings, *, failure_reason="", unpriced=(), agent_runs=(), skipped=()):
    """The finished review."""
    lines = [HEADER, ""]

    if failure_reason:
        lines += [
            "The review could not be completed.",
            "",
            f"> {failure_reason}",
            "",
            "Push a new commit to try again, or re-run it from the CodeSage dashboard.",
            "",
        ]
    elif not findings:
        lines += [
            f"No issues found in `{_short(review.head_sha)}`.",
            "",
        ]
    else:
        blocking = [f for f in findings if f.severity == "blocking"]
        nits = [f for f in findings if f.severity != "blocking"]

        summary = []
        if blocking:
            summary.append(f"**{len(blocking)} blocking**")
        if nits:
            summary.append(f"{len(nits)} nit{'s' if len(nits) != 1 else ''}")
        lines += [
            f"Reviewed `{_short(review.head_sha)}` — {', '.join(summary)}.",
            "",
        ]

        for group, heading in ((blocking, "Blocking"), (nits, "Nits")):
            if not group:
                continue
            lines.append(f"### {heading}")
            lines.append("")
            for finding in group:
                lines.append(_render_finding(finding))
                lines.append("")

    disclosure = _render_disclosure(review)
    if disclosure:
        lines += [disclosure, ""]

    agents = _render_agents(agent_runs, skipped)
    if agents:
        lines += [agents, ""]

    lines += [
        "---",
        format_footer(
            review.duration_ms,
            review.estimated_cost_inr,
            review.model_used,
            review.used_fallback,
            unpriced=unpriced,
        ),
    ]

    return "\n".join(lines).strip() + "\n"


def _render_finding(finding):
    label = SEVERITY_LABEL.get(finding.severity, finding.severity)
    category = f" · {finding.category}" if finding.category else ""
    return f"- **`{finding.file_path}:{finding.line}`** — {label}{category}\n  {finding.message}"


def _render_disclosure(review):
    """Say plainly what was left out, rather than letting silence imply coverage."""
    notes = []

    if review.truncated:
        notes.append("The diff was larger than the review budget, so only part of it was examined.")

    skipped = list(review.skipped_files or [])
    if skipped:
        shown = ", ".join(f"`{path}`" for path in skipped[:10])
        more = f" and {len(skipped) - 10} more" if len(skipped) > 10 else ""
        notes.append(f"Not reviewed (generated, binary or too large): {shown}{more}.")

    if not notes:
        return ""
    return "\n".join(f"> {note}" for note in notes)


def _short(sha):
    return (sha or "unknown")[:7]


AGENT_LABELS = {
    "diff_intent": "Diff/Intent",
    "static_analysis": "Static analysis",
    "security": "Security",
    "grounding": "Codebase grounding",
    "test_coverage": "Test coverage",
}


def _render_agents(agent_runs, skipped):
    """Say which agents ran and which did not.

    A six-agent review that quietly ran four looks identical to one that ran six
    and found less, unless it says so. Collapsed into a details block so the
    findings stay the first thing a reviewer reads.
    """
    if not agent_runs:
        return ""

    rows = []
    for run in agent_runs:
        label = AGENT_LABELS.get(run.name, run.name)
        if run.skipped_reason:
            rows.append(f"| {label} | skipped | {run.skipped_reason} |")
        elif run.error:
            rows.append(f"| {label} | failed | {run.error[:90]} |")
        else:
            plural = "" if run.findings_count == 1 else "s"
            detail = f"{run.findings_count} finding{plural}"
            if run.model:
                detail += f" · `{run.model}`"
            if run.used_fallback:
                detail += " (fallback)"
            rows.append(f"| {label} | ok | {detail} |")

    note = ""
    if skipped:
        note = (
            "\n\nSome agents were skipped to stay inside the review's token budget; "
            "the highest-priority ones run first."
        )

    table = "\n".join(rows)
    return (
        "<details>\n<summary>Agents</summary>\n\n"
        "| Agent | Status | Detail |\n|---|---|---|\n"
        f"{table}{note}\n\n</details>"
    )


def render_degraded(review, reason, agent_runs=()):
    """The demo-mode fallback comment (spec section 5).

    Deliberately unlike a review: no findings section, no "no issues found", and an
    explicit statement that the change was NOT reviewed. A degraded result that
    reads like a clean review is worse than no comment at all, because it tells a
    reviewer the change was checked when it was not.
    """
    lines = [
        HEADER,
        "",
        "> **Degraded mode — automated review unavailable.**",
        ">",
        "> No language model could be reached for this change, so **this pull "
        "request has not been reviewed**. Please do not read this comment as "
        "approval.",
        "",
        f"Commit: `{_short(review.head_sha)}`",
        "",
    ]

    if reason:
        lines += [f"Reason: {reason[:300]}", ""]

    if any(run.succeeded and not run.provider for run in agent_runs):
        lines += [
            "Local static analysis did run. It is a partial signal only, and is "
            "not a substitute for the review.",
            "",
        ]

    lines += [
        "Push a new commit to retry, or re-run the review from the CodeSage "
        "dashboard once quota is available.",
    ]
    return "\n".join(lines).strip() + "\n"
