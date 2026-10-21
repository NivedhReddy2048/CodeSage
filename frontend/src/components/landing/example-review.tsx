// A server component: static markup, nothing to hydrate, no JavaScript shipped.

import { Clock, FlaskConical } from "lucide-react";

import { Inr } from "@/components/inr";
import { DiffViewer } from "@/components/review/diff-viewer";
import { StatusBadge } from "@/components/status-badge";
import { AGENT_LABELS, formatDuration } from "@/lib/format";
import type { ReviewFinding } from "@/lib/types";

/**
 * A review as the review page shows one, drawn by the same DiffViewer from fixed
 * sample data. Nothing here fetches: no API client, no socket, no image. It is
 * labelled "Example" so it is never mistaken for a real repository's review.
 *
 * The finding is shaped like a real grounding finding: a citation in the
 * `path:start-end` form the citation checker emits, appended to the message, and a
 * message that names the existing symbol the check looks for.
 */

export const EXAMPLE_DIFF = `diff --git a/app/reports.py b/app/reports.py
--- a/app/reports.py
+++ b/app/reports.py
@@ -10,4 +10,10 @@ from app.models import User

 def active_users(users):
     return [u for u in users if u.active]

+def user_report(users):
+    rows = []
+    for i in range(len(users) + 1):
+        rows.append(format_row(users[i]))
+    return rows
+
`;

const CITATION = "app/exports.py:22-31";

export const EXAMPLE_FINDINGS: ReviewFinding[] = [
  {
    id: 1,
    agent: "grounding",
    severity: "blocking",
    category: "correctness",
    file_path: "app/reports.py",
    line: 16,
    placement: "inline",
    message:
      "range(len(users) + 1) runs one index past the end, so users[i] raises IndexError on the last pass. The existing `export_rows` iterates the list directly instead. (see " +
      CITATION +
      ")",
    citation: CITATION,
    dismissed: false,
  },
];

/** Sample per-agent timings. Synthesis is a deterministic merge, not a model call. */
export const EXAMPLE_TELEMETRY = [
  { agent: "diff_intent", ms: 900 },
  { agent: "static_analysis", ms: 400, note: "ran ruff, bandit" },
  { agent: "security", ms: 1600 },
  { agent: "grounding", ms: 2600 },
  { agent: "test_coverage", ms: 1400 },
];

export function ExampleReview() {
  return (
    <div className="overflow-clip rounded-2xl border bg-surface-1 shadow-card">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b bg-surface-2/60 px-4 py-3">
        <span className="inline-flex items-center gap-1 rounded-md border border-status-running-border bg-status-running-bg px-2 py-0.5 text-xs font-semibold text-status-running">
          <FlaskConical aria-hidden="true" className="size-3.5" />
          Example
        </span>
        <span className="min-w-0 truncate font-mono text-[0.8125rem] text-fg">acme/payments-api#42</span>
        <span className="min-w-0 flex-1 truncate text-sm text-fg-secondary">Add user lookup helpers for reporting</span>
        <StatusBadge kind="done" />
        <span className="inline-flex items-center gap-1 rounded-full border border-status-blocking-border bg-status-blocking-bg px-2 py-0.5 text-xs font-medium text-status-blocking">
          1 blocking
        </span>
      </div>

      <div className="p-3 sm:p-4">
        <DiffViewer diff={EXAMPLE_DIFF} findings={EXAMPLE_FINDINGS} />
      </div>

      <div className="border-t bg-surface-2/40 px-4 py-3">
        <p className="mb-2 text-xs font-medium tracking-[0.06em] text-fg-secondary uppercase">Per-agent telemetry</p>
        <ul aria-label="Per-agent telemetry" className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
          {EXAMPLE_TELEMETRY.map(({ agent, ms, note }) => (
            <li key={agent} className="rounded-lg border bg-surface-1 px-3 py-2">
              <span className="block truncate text-xs font-medium text-fg">{AGENT_LABELS[agent]}</span>
              <span className="mt-0.5 flex items-center gap-1 font-mono text-xs text-fg-secondary tabular-nums">
                <Clock aria-hidden="true" className="size-3" />
                {formatDuration(ms)}
                {note ? <span className="truncate font-sans">· {note}</span> : null}
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-3 font-mono text-xs text-fg-secondary tabular-nums">
          Reviewed in 4.2 s · est. <Inr />0.07 at paid-tier rates · actual spend <Inr />0
        </p>
      </div>
    </div>
  );
}
