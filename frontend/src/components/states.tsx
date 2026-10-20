import { CircleAlert, Inbox, RotateCw, type LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * Loading, empty and error states. Every page uses these three rather than ad-hoc
 * text, so a reader always gets the same cue for "still loading", "nothing here
 * yet" and "something went wrong, here is what you can do".
 */

/**
 * A small drawing for an empty state: two stacked cards with the state's icon on a
 * brand badge. Decorative; the title says what is (not) there.
 */
function EmptyIllustration({ icon: Icon }: { icon: LucideIcon }) {
  return (
    <div aria-hidden="true" className="relative mb-1 h-[72px] w-[120px]">
      <svg viewBox="0 0 120 72" className="absolute inset-0 size-full">
        <rect x="22" y="2" width="76" height="46" rx="10" className="fill-surface-2 stroke-[color:var(--border-default)]" />
        <rect x="10" y="14" width="100" height="56" rx="11" className="fill-surface-1 stroke-[color:var(--border-default)]" />
        <rect x="24" y="48" width="44" height="4" rx="2" className="fill-[color:var(--border-default)]" />
        <rect x="24" y="58" width="68" height="4" rx="2" className="fill-[color:var(--border-subtle)]" />
      </svg>
      <span className="absolute top-[20px] left-1/2 flex size-8 -translate-x-1/2 items-center justify-center rounded-lg border border-border-brand bg-brand-tinted text-brand">
        <Icon className="size-4" />
      </span>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  icon: Icon = Inbox,
  action,
  className,
}: {
  title: string;
  description?: React.ReactNode;
  icon?: LucideIcon;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border-strong/60 bg-surface-2/40 px-6 py-8 text-center",
        className,
      )}
    >
      <EmptyIllustration icon={Icon} />
      <p className="font-medium text-fg">{title}</p>
      {description ? (
        <p className="max-w-sm text-sm text-fg-secondary">{description}</p>
      ) : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
  className,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex gap-3 rounded-xl border border-status-blocking-border bg-status-blocking-bg px-4 py-3",
        className,
      )}
    >
      <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-status-blocking" />
      <div className="min-w-0 text-sm">
        <p className="font-medium text-fg">{title}</p>
        <p className="mt-0.5 text-fg-secondary">{message}</p>
        {onRetry ? (
          <Button variant="outline" size="sm" onClick={onRetry} className="mt-2.5">
            <RotateCw aria-hidden="true" className="size-3.5" />
            Try again
          </Button>
        ) : null}
      </div>
    </div>
  );
}

const CALLOUT_TONE = {
  blocking: "border-status-blocking-border bg-status-blocking-bg [&>svg]:text-status-blocking",
  nit: "border-status-nit-border bg-status-nit-bg [&>svg]:text-status-nit",
  info: "border-status-running-border bg-status-running-bg [&>svg]:text-status-running",
} as const;

/**
 * A structured notice: an icon in the tone's colour, a title, and a body in
 * secondary text. Used for what a reader must know before trusting the page - a
 * degraded or failed run, a fallback, a partial diff. `role="alert"` only for the
 * serious ones.
 */
export function Callout({
  tone,
  icon: Icon,
  title,
  children,
  role,
  className,
}: {
  tone: keyof typeof CALLOUT_TONE;
  icon: LucideIcon;
  title: string;
  children?: React.ReactNode;
  role?: "alert" | "status";
  className?: string;
}) {
  return (
    <div role={role} className={cn("flex gap-3 rounded-xl border px-4 py-3", CALLOUT_TONE[tone], className)}>
      <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 text-sm">
        <p className="font-medium text-fg">{title}</p>
        {children ? <div className="mt-0.5 text-fg-secondary">{children}</div> : null}
      </div>
    </div>
  );
}

/** Placeholder rows shaped like the content that is loading. */
export function ListSkeleton({ rows = 4, label = "Loading" }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label} className="space-y-3">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="flex items-center gap-3">
          <Skeleton className="size-8 rounded-full" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-4 w-2/5" />
            <Skeleton className="h-3 w-3/5" />
          </div>
        </div>
      ))}
      <span className="sr-only">{label}...</span>
    </div>
  );
}

export function TableSkeleton({
  rows = 5,
  columns = 4,
  label = "Loading",
}: {
  rows?: number;
  columns?: number;
  label?: string;
}) {
  return (
    <div role="status" aria-label={label} className="space-y-2">
      {Array.from({ length: rows }, (_, row) => (
        <div key={row} className="grid gap-3" style={{ gridTemplateColumns: `repeat(${columns}, 1fr)` }}>
          {Array.from({ length: columns }, (_, column) => (
            <Skeleton key={column} className="h-5" />
          ))}
        </div>
      ))}
      <span className="sr-only">{label}...</span>
    </div>
  );
}

export function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error && error.message ? error.message : fallback;
}
