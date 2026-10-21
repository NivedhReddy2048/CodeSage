"use client";

import { findingAnchor } from "@/components/review/diff-viewer";
import { StatusBadge } from "@/components/status-badge";
import { EmptyState } from "@/components/states";
import { AGENT_LABELS } from "@/lib/format";
import type { ReviewFinding } from "@/lib/types";
import { cn } from "@/lib/utils";

const PLACEMENT_LABELS: Record<ReviewFinding["placement"], string> = {
  inline: "Changed line",
  existing: "Existing code",
  general: "General",
};

/** file:line, or just the file for a finding with no honest line (general). */
export function findingLocation(finding: Pick<ReviewFinding, "file_path" | "line" | "placement">) {
  return finding.placement === "general" ? finding.file_path : `${finding.file_path}:${finding.line}`;
}

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
      <h3 className="mb-2 flex items-center gap-2 text-[0.6875rem] font-medium tracking-[0.06em] text-fg-secondary uppercase">
        {title}
        <span className="rounded-full border bg-surface-1 px-1.5 font-mono tabular-nums normal-case">{findings.length}</span>
      </h3>
      <ul className="space-y-2">
        {findings.map((finding) => (
          <li
            key={finding.id}
            className={cn(
              "rounded-lg border border-l-[3px] bg-surface-1 p-3 text-sm shadow-card",
              finding.severity === "blocking" ? "border-l-status-blocking" : "border-l-status-nit",
            )}
          >
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge kind={finding.severity} />
              {anchored.has(finding.id) ? (
                <button
                  type="button"
                  onClick={() => jumpTo(finding.id)}
                  className="truncate rounded-sm font-mono text-xs text-fg underline-offset-4 hover:text-brand hover:underline"
                >
                  {findingLocation(finding)}
                </button>
              ) : (
                <span className="truncate font-mono text-xs text-fg-secondary">
                  {findingLocation(finding)}
                </span>
              )}
              {finding.placement && finding.placement !== "inline" ? (
                <span className="rounded-md border bg-surface-2 px-1.5 py-0.5 text-xs text-fg-secondary">
                  {PLACEMENT_LABELS[finding.placement]}
                </span>
              ) : null}
            </div>
            <p className="mt-1.5 line-clamp-3 text-fg">{finding.message}</p>
            <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-fg-secondary">
              <span className="rounded-md border bg-surface-2 px-1.5 py-0.5 font-medium">
                {AGENT_LABELS[finding.agent] ?? finding.agent}
              </span>
              {finding.category ? <span>{finding.category}</span> : null}
              {!anchored.has(finding.id) ? <span>· not on a line the diff shows</span> : null}
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
