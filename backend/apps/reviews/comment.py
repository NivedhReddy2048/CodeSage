"""Render the review as the body of the bot's PR comment.

Two constraints shape this:

1. **It must change on every run.** Phase 2's verification showed GitHub no-ops a
   PATCH whose body is byte-identical and does not move `updated_at`, so a constant
   body makes a re-review invisible. Including the reviewed head SHA guarantees every
   `synchronize` is a real edit.

2. **It must disclose what it did not look at.** A short review of a truncated diff
   looks identical to a short review of clean code unless it says otherwise.

3. **It is public, so it never carries a raw error.** Provider errors include
   response bodies, account and quota details, and request URLs. The comment gets a
   short human reason from `public_reason`; the full error is logged and stored on
   the Review, where the review page shows it.
"""

from apps.reviews.pricing import format_footer

SEVERITY_LABEL = {"blocking": "Blocking", "nit": "Nit"}

HEADER = "## CodeSage review"

ACK_BODY = (
    "**CodeSage is reviewing this PR...**\n\n"
    "A multi-agent review is running. This comment will be updated with the findings "
    "when it completes."
)


PROVIDERS_UNAVAILABLE = "AI providers unavailable"
DIFF_UNAVAILABLE = "Could not fetch this pull request's diff from GitHub"
DETAILS_NOTE = "Full details are recorded on the review in the CodeSage dashboard."


def public_reason(error):
    """A short, human reason that is safe to post on a public pull request.

    Deliberately coarse. The specifics a raw error carries - HTTP bodies, quota
    numbers, key prefixes, URLs - help an operator and nobody reading the PR, and
    some of them should not be published at all.
    """
    text = (error or "").lower()
    if not text:
        return ""
    if "no llm provider is configured" in text or "no provider configured" in text:
        return "No AI provider is configured"
    if text.startswith("schema") or "schema:" in text:
        return "The AI response was not in the expected format"
    if text.startswith("retrieval failed"):
        return "Code search was unavailable"
    if text.startswith("every agent was skipped"):
        return "Every agent was skipped to stay inside the token budget"
    if any(
        marker in text
        for marker in ("groq", "gemini", "circuit", "http ", "timed out", "network", "provider")
    ):
        return PROVIDERS_UNAVAILABLE
    return "An internal error occurred"


def render_running(head_sha):
    """Shown while a review is in flight, naming the commit being reviewed."""
    return (
        f"{HEADER}\n\n"
        f"Reviewing `{_short(head_sha)}`...\n\n"
        "This comment will be updated with the findings when the review completes."
    )


def render(
    review,
    findings,
    *,
    failure_reason="",
    public_reason=None,
    unpriced=(),
    agent_runs=(),
    skipped=(),
    inline=None,
):
    """The finished review.

    `failure_reason` is the raw internal reason and is never printed; it is mapped
    to a short public one unless the caller supplies `public_reason` itself.
    """
    lines = [HEADER, ""]

    if failure_reason:
        shown = public_reason or _public_reason(failure_reason)
        lines += [
            "The review could not be completed.",
            "",
            f"> {shown}.",
            "",
            "Push a new commit to try again, or re-run it from the CodeSage dashboard. "
            + DETAILS_NOTE,
            "",
        ]
    elif not findings:
        lines += [
            f"No issues found in `{_short(review.head_sha)}`.",
            "",
        ]
        inline_note = _render_inline_note(inline)
        if inline_note:
            lines += [inline_note, ""]
    else:
        existing = [f for f in findings if _placement(f) == "existing"]
        general = [f for f in findings if _placement(f) == "general"]
        anchored = [f for f in findings if _placement(f) == "inline"]
        counted = anchored + general
        blocking = [f for f in anchored if f.severity == "blocking"]
        nits = [f for f in anchored if f.severity != "blocking"]

        total_blocking = sum(1 for f in counted if f.severity == "blocking")
        total_nits = len(counted) - total_blocking
        summary = []
        if total_blocking:
            summary.append(f"**{total_blocking} blocking**")
        if total_nits:
            summary.append(f"{total_nits} nit{'s' if total_nits != 1 else ''}")
        if existing:
            summary.append(f"{len(existing)} about existing code")
        lines += [
            f"Reviewed `{_short(review.head_sha)}` — {', '.join(summary)}.",
            "",
        ]

        for group, heading in ((blocking, "Blocking"), (nits, "Nits"), (general, "General")):
            if not group:
                continue
            lines.append(f"### {heading}")
            lines.append("")
            for finding in group:
                lines.append(_render_finding(finding))
                lines.append("")

        if existing:
            # Collapsed: worth knowing, but the author did not write these lines.
            lines += [
                "<details>",
                f"<summary>Existing code (not introduced by this PR) · {len(existing)}</summary>",
                "",
            ]
            for finding in existing:
                lines.append(_render_finding(finding))
                lines.append("")
            lines += ["</details>", ""]

        inline_note = _render_inline_note(inline)
        if inline_note:
            lines += [inline_note, ""]

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


def _render_inline_note(inline):
    superseded = getattr(inline, "superseded", 0)
    if inline is None or not (inline.posted or inline.duplicates or superseded):
        return ""
    parts = []
    if inline.posted:
        parts.append(f"{inline.posted} new inline comment{'s' if inline.posted != 1 else ''}")
    if inline.duplicates:
        parts.append(f"{inline.duplicates} already on the diff from an earlier run")
    if superseded:
        parts.append(f"{superseded} earlier comment{'s' if superseded != 1 else ''} superseded")
    return f"_Inline on the changed lines: {', '.join(parts)}._"


def _placement(finding):
    placement = getattr(finding, "placement", "inline")
    return placement if placement in {"inline", "existing", "general"} else "inline"


def _render_finding(finding):
    """One bullet. An inline finding names exactly the line its inline comment is on;
    a general one has no honest line, so it names only the file."""
    label = SEVERITY_LABEL.get(finding.severity, finding.severity)
    category = f" · {finding.category}" if finding.category else ""
    where = (
        finding.file_path
        if _placement(finding) == "general"
        else f"{finding.file_path}:{finding.line}"
    )
    return f"- **`{where}`** — {label}{category}\n  {finding.message}"


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
            rows.append(f"| {label} | skipped | {_cell(run.skipped_reason)} |")
        elif not run.succeeded:
            # Keyed on `succeeded`, not on whether an error string happens to be
            # set: an agent that got nothing usable back has failed whether or not
            # anyone attached a message, and must never read as "ok, 0 findings".
            reason = _public_reason(run.error) or "No usable output"
            rows.append(f"| {label} | failed | {reason} |")
        else:
            rows.append(f"| {label} | ok | {_ok_detail(run)} |")

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


def _ok_detail(run):
    plural = "" if run.findings_count == 1 else "s"
    parts = [f"{run.findings_count} finding{plural}"]
    if run.detail:
        parts.append(_cell(run.detail))
    if run.model:
        served = f"`{run.model}`"
        if run.provider:
            served += f" via {run.provider}"
        requested = getattr(run, "requested_model", "")
        if run.used_fallback:
            served += f" (fallback for `{requested}`)" if requested else " (fallback)"
        parts.append(served)
    return " · ".join(parts)


def _cell(text):
    """Keep free text from breaking the markdown table."""
    return " ".join(str(text).replace("|", "/").split())[:160]


# Module-level alias: `render` takes a parameter named `public_reason`.
_public_reason = public_reason


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
        lines += [f"Reason: {public_reason(reason) or PROVIDERS_UNAVAILABLE}. {DETAILS_NOTE}", ""]

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
