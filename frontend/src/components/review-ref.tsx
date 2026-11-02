import { History, RotateCcw } from "lucide-react";

import { formatInr, formatInrExact } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Which commit a review read, and what started it when it was not a webhook:
 * "abc1234 · Re-run" (a person asked) or "abc1234 · Catch-up" (the webhook was lost
 * while the service slept). Two reviews of one PR are otherwise indistinguishable.
 */
const TRIGGER_TAGS: Record<string, { label: string; title: string; icon: typeof RotateCcw }> = {
  rerun: { label: "Re-run", title: "Started by a re-run, not by a push", icon: RotateCcw },
  catchup: {
    label: "Catch-up",
    title: "Its webhook was missed while CodeSage slept; picked up on waking",
    icon: History,
  },
};

export function ReviewRef({
  sha,
  trigger,
  className,
}: {
  sha: string;
  trigger?: string;
  className?: string;
}) {
  const tag = TRIGGER_TAGS[trigger ?? ""];
  if (!sha && !tag) return null;
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs text-fg-secondary", className)}>
      {sha ? (
        <code className="font-mono tabular-nums" title={`Head commit ${sha}`}>
          {sha.slice(0, 7)}
        </code>
      ) : null}
      {tag ? (
        <span
          className="inline-flex items-center gap-1 rounded-md border bg-surface-2 px-1.5 py-0.5 font-medium"
          title={tag.title}
        >
          <tag.icon aria-hidden="true" className="size-3" />
          {tag.label}
        </span>
      ) : null}
    </span>
  );
}

/** A cost estimate at two decimals, with the exact stored figure on hover. */
export function Cost({ value }: { value: string | number | null | undefined }) {
  const shown = formatInr(value, 2);
  if (shown === "-") return <>-</>;
  const exact = formatInrExact(value);
  return (
    <span title={`Exact estimate: ${exact}`}>
      {shown}
    </span>
  );
}
