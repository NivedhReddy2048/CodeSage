import { RotateCcw } from "lucide-react";

import { formatInr, formatInrExact } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Which commit a review read, and whether a person asked for it: "abc1234 · Re-run".
 * Two reviews of one PR are otherwise indistinguishable in a list.
 */
export function ReviewRef({
  sha,
  trigger,
  className,
}: {
  sha: string;
  trigger?: string;
  className?: string;
}) {
  if (!sha && trigger !== "rerun") return null;
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs text-fg-secondary", className)}>
      {sha ? (
        <code className="font-mono tabular-nums" title={`Head commit ${sha}`}>
          {sha.slice(0, 7)}
        </code>
      ) : null}
      {trigger === "rerun" ? (
        <span
          className="inline-flex items-center gap-1 rounded-md border bg-surface-2 px-1.5 py-0.5 font-medium"
          title="Started by a re-run, not by a push"
        >
          <RotateCcw aria-hidden="true" className="size-3" />
          Re-run
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
