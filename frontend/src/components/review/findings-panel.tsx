"use client";

import { findingAnchor } from "@/components/review/diff-viewer";
import { StatusBadge } from "@/components/status-badge";
import { EmptyState } from "@/components/states";
import { AGENT_LABELS } from "@/lib/format";
import type { ReviewFinding } from "@/lib/types";

function jumpTo(id: number) {
  const target = document.getElementById(findingAnchor(id));
  if (!target) return;
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  // Move focus too, so a keyboard user lands where they asked to go.
  target.setAttribute("tabindex", "-1");
  target.focus({ preventScroll: true });
}

function Group({
  title,
  findings,
  anchored,
}: {
  title: string;
  findings: ReviewFinding[];
  anchored: Set<number>;
}) {
  if (findings.length === 0) return null;
  return (
    <section aria-label={`${title} findings`}>
      <h3 className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">
        {title} ({findings.length})
      </h3>
      <ul className="space-y-2">
        {findings.map((finding) => (
          <li key={finding.id} className="rounded-md border p-2.5 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge kind={finding.severity} />
              {anchored.has(finding.id) ? (
                <button
                  type="button"
                  onClick={() => jumpTo(finding.id)}
                  className="truncate font-mono text-xs underline-offset-4 hover:underline"
                >
                  {finding.file_path}:{finding.line}
                </button>
              ) : (
                <span className="truncate font-mono text-xs">
                  {finding.file_path}:{finding.line}
                </span>
              )}
            </div>
            <p className="mt-1 line-clamp-3">{finding.message}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {AGENT_LABELS[finding.agent] ?? finding.agent}
              {finding.category ? ` · ${finding.category}` : ""}
              {!anchored.has(finding.id) ? " · not on a line the diff shows" : ""}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Findings grouped by severity; each anchored one jumps to its line in the diff. */
export function FindingsPanel({
  findings,
  unanchored,
  status,
}: {
  findings: ReviewFinding[];
  unanchored: ReviewFinding[];
  status: string;
}) {
  if (status === "pending" || status === "running") {
    // Never "no findings" while agents are still working: that reads as a clean
    // review of a change nobody has finished looking at.
    return (
      <EmptyState
        title="Review in progress"
        description="Findings appear here when the agents finish."
      />
    );
  }

  if (findings.length === 0) {
    return (
      <EmptyState
        title={status === "done" ? "No issues found" : "No findings"}
        description={
          status === "done"
            ? "Every agent that ran looked at this change and reported nothing."
            : "This review produced no findings."
        }
      />
    );
  }

  const off = new Set(unanchored.map((finding) => finding.id));
  const anchored = new Set(findings.filter((f) => !off.has(f.id)).map((f) => f.id));

  return (
    <div className="space-y-5">
      <Group title="Blocking" findings={findings.filter((f) => f.severity === "blocking")} anchored={anchored} />
      <Group title="Nits" findings={findings.filter((f) => f.severity !== "blocking")} anchored={anchored} />
    </div>
  );
}
