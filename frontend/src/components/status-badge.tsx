import {
  CircleCheck,
  CircleDot,
  CircleMinus,
  CircleX,
  Clock,
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
  | "failed"
  | "skipped";

type Style = { label: string; icon: LucideIcon; tone: string; spin?: boolean };

// Each tone is a token pair from globals.css whose text clears 5.5:1 against both
// the badge and the card behind it, in light and dark. Every badge also carries an
// icon and a word, so the status never rests on colour alone.
const STYLES: Record<StatusKind, Style> = {
  blocking: {
    label: "Blocking",
    icon: OctagonAlert,
    tone: "bg-status-blocking-bg text-status-blocking border-status-blocking/25",
  },
  nit: {
    label: "Nit",
    icon: CircleDot,
    tone: "bg-status-nit-bg text-status-nit border-status-nit/25",
  },
  degraded: {
    label: "Degraded",
    icon: TriangleAlert,
    tone: "bg-status-degraded-bg text-status-degraded border-status-degraded/25",
  },
  fallback: {
    label: "Fallback",
    icon: Shuffle,
    tone: "bg-status-fallback-bg text-status-fallback border-status-fallback/25",
  },
  ok: {
    label: "OK",
    icon: CircleCheck,
    tone: "bg-status-ok-bg text-status-ok border-status-ok/25",
  },
  done: {
    label: "Done",
    icon: CircleCheck,
    tone: "bg-status-ok-bg text-status-ok border-status-ok/25",
  },
  running: {
    label: "Running",
    icon: LoaderCircle,
    tone: "bg-status-running-bg text-status-running border-status-running/25",
    spin: true,
  },
  pending: {
    label: "Pending",
    icon: Clock,
    tone: "bg-status-nit-bg text-status-nit border-status-nit/25",
  },
  failed: {
    label: "Failed",
    icon: CircleX,
    tone: "bg-status-blocking-bg text-status-blocking border-status-blocking/25",
  },
  skipped: {
    label: "Skipped",
    icon: CircleMinus,
    tone: "bg-status-nit-bg text-status-nit border-status-nit/25",
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
        "inline-flex h-6 shrink-0 items-center gap-1 rounded-full border px-2 text-xs font-medium whitespace-nowrap",
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

/** A review's headline status: degraded outranks the raw status it sits on. */
export function reviewStatusKind(review: {
  status: string;
  degraded: boolean;
}): StatusKind {
  if (review.degraded) return "degraded";
  if (review.status === "done") return "done";
  if (review.status === "running") return "running";
  if (review.status === "failed") return "failed";
  return "pending";
}
