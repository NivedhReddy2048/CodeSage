import {
  CircleCheck,
  CircleDot,
  CircleMinus,
  CircleX,
  Clock,
  ClockAlert,
  LoaderCircle,
  OctagonAlert,
  Shuffle,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

export type StatusKind =
  | "blocking"
  | "nit"
  | "degraded"
  | "fallback"
  | "ok"
  | "done"
  | "running"
  | "pending"
  | "stalled"
  | "failed"
  | "skipped";

type Style = { label: string; icon: LucideIcon; tone: string; spin?: boolean };

// Each tone is a token triple from globals.css (text, fill, outline). The text clears
// 4.5:1 on its fill over the canvas, a card and surface-2, in light and dark - the
// contrast test checks every one. Nit, degraded, fallback and stalled share amber, and every
// badge carries an icon and a word, so the status never rests on colour alone.
const STYLES: Record<StatusKind, Style> = {
  blocking: {
    label: "Blocking",
    icon: OctagonAlert,
    tone: "bg-status-blocking-bg text-status-blocking border-status-blocking-border",
  },
  nit: {
    label: "Nit",
    icon: CircleDot,
    tone: "bg-status-nit-bg text-status-nit border-status-nit-border",
  },
  degraded: {
    label: "Degraded",
    icon: TriangleAlert,
    tone: "bg-status-degraded-bg text-status-degraded border-status-degraded-border",
  },
  fallback: {
    label: "Fallback",
    icon: Shuffle,
    tone: "bg-status-fallback-bg text-status-fallback border-status-fallback-border",
  },
  ok: {
    label: "OK",
    icon: CircleCheck,
    tone: "bg-status-ok-bg text-status-ok border-status-ok-border",
  },
  done: {
    label: "Done",
    icon: CircleCheck,
    tone: "bg-status-ok-bg text-status-ok border-status-ok-border",
  },
  running: {
    label: "Running",
    icon: LoaderCircle,
    tone: "bg-status-running-bg text-status-running border-status-running-border",
    spin: true,
  },
  pending: {
    label: "Pending",
    icon: Clock,
    tone: "bg-status-neutral-bg text-status-neutral border-status-neutral-border",
  },
  // Pending or running long past any real review: no worker has it.
  stalled: {
    label: "Stalled",
    icon: ClockAlert,
    tone: "bg-status-degraded-bg text-status-degraded border-status-degraded-border",
  },
  failed: {
    label: "Failed",
    icon: CircleX,
    tone: "bg-status-blocking-bg text-status-blocking border-status-blocking-border",
  },
  skipped: {
    label: "Skipped",
    icon: CircleMinus,
    tone: "bg-status-neutral-bg text-status-neutral border-status-neutral-border",
  },
};

export function StatusBadge({
  kind,
  label,
  className,
}: {
  kind: StatusKind;
  /** Overrides the default word, e.g. "3/5 agents". */
  label?: string;
  className?: string;
}) {
  const style = STYLES[kind];
  const Icon = style.icon;
  return (
    <span
      data-status={kind}
      className={cn(
        "inline-flex h-6 shrink-0 items-center gap-1 rounded-full border px-2 text-micro whitespace-nowrap",
        style.tone,
        className,
      )}
    >
      <Icon
        aria-hidden="true"
        className={cn("size-3.5", style.spin && "animate-spin motion-reduce:animate-none")}
      />
      {label ?? style.label}
    </span>
  );
}

/**
 * A review's headline status: degraded outranks the raw status it sits on, and a
 * stalled review is not shown as merely queued or running.
 */
export function reviewStatusKind(review: {
  status: string;
  degraded: boolean;
  stalled?: boolean;
}): StatusKind {
  if (review.degraded) return "degraded";
  if (review.status === "done") return "done";
  if (review.status === "failed") return "failed";
  if (review.stalled) return "stalled";
  if (review.status === "running") return "running";
  return "pending";
}
