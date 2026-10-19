"use client";

import { StatusBadge, reviewStatusKind } from "@/components/status-badge";
import type { ProgressTransport } from "@/hooks/use-review-progress";
import type { ReviewProgress } from "@/lib/types";

/**
 * "Reviewing... 3/5 agents" while the pipeline runs, then the final status. Lives in
 * an aria-live region so a screen reader hears progress without polling the page.
 */
export function ReviewStatusPill({
  status,
  degraded,
  progress,
  transport,
}: {
  status: string;
  degraded: boolean;
  progress: ReviewProgress | null;
  transport: ProgressTransport;
}) {
  const liveStatus = progress?.status ?? status;
  const running = liveStatus === "pending" || liveStatus === "running";

  return (
    <span role="status" aria-live="polite" className="inline-flex items-center gap-2">
      {running ? (
        <StatusBadge
          kind={liveStatus === "pending" ? "pending" : "running"}
          label={
            progress
              ? `Reviewing... ${progress.completed}/${progress.total} agents`
              : liveStatus === "pending"
                ? "Queued"
                : "Reviewing..."
          }
        />
      ) : (
        <StatusBadge kind={reviewStatusKind({ status: liveStatus, degraded: progress?.degraded ?? degraded })} />
      )}
      {running && transport === "polling" ? (
        <span className="text-xs text-muted-foreground">live updates paused, checking every few seconds</span>
      ) : null}
    </span>
  );
}
