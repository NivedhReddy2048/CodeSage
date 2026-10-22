"use client";

import { StatusBadge, reviewStatusKind } from "@/components/status-badge";
import type { ProgressTransport } from "@/hooks/use-review-progress";
import type { ReviewProgress } from "@/lib/types";

/**
 * "Reviewing... 3/6 agents" while the pipeline runs, then the final status. Lives in
 * an aria-live region so a screen reader hears progress without polling the page.
 *
 * A review the API calls stalled is not pulsed at as if work were happening: nothing
 * is, until a worker picks it up - which a live progress event would show.
 */
export function ReviewStatusPill({
  status,
  degraded,
  stalled = false,
  progress,
  transport,
}: {
  status: string;
  degraded: boolean;
  stalled?: boolean;
  progress: ReviewProgress | null;
  transport: ProgressTransport;
}) {
  const liveStatus = progress?.status ?? status;
  const inFlight = liveStatus === "pending" || liveStatus === "running";
  const isStalled = inFlight && stalled && progress?.type !== "review.progress";
  const running = inFlight && !isStalled;

  if (isStalled) {
    return (
      <span role="status" aria-live="polite" className="inline-flex items-center gap-2">
        <StatusBadge kind="stalled" />
        <span className="text-xs text-fg-secondary">
          Not finished after 15 minutes. The review worker may not be running.
        </span>
      </span>
    );
  }

  return (
    <span role="status" aria-live="polite" className="inline-flex items-center gap-2">
      {running ? (
        // A soft pulse beside the badge while agents work: decorative, and still
        // under reduced motion.
        <span aria-hidden="true" className="relative flex size-2">
          <span className="absolute inline-flex size-full rounded-full bg-status-running opacity-60 motion-safe:animate-ping" />
          <span className="relative inline-flex size-2 rounded-full bg-status-running" />
        </span>
      ) : null}
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
        <span className="text-xs text-fg-secondary">live updates paused, checking every few seconds</span>
      ) : null}
    </span>
  );
}
