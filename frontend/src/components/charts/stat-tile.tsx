import type { LucideIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";

/**
 * A headline number: an icon badge, the label (sentence case, no colon), the value
 * in mono tabular figures, one line of context, and optionally a small summary mark
 * (a breakdown bar or a sparkline) under it. The number is the point; the mark only
 * shows its shape.
 */
export function StatTile({
  label,
  value,
  context,
  icon: Icon,
  children,
}: {
  label: string;
  value: React.ReactNode;
  context?: React.ReactNode;
  icon?: LucideIcon;
  /** A BreakdownBar or Sparkline. */
  children?: React.ReactNode;
}) {
  return (
    <Card size="sm" className="h-full">
      <CardContent className="flex h-full flex-col">
        <dl className="flex-1">
          <div className="flex items-center justify-between gap-2">
            <dt className="text-sm text-fg-secondary">{label}</dt>
            {Icon ? (
              <span
                aria-hidden="true"
                className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-border-brand bg-brand-tinted text-brand"
              >
                <Icon className="size-3.5" />
              </span>
            ) : null}
          </div>
          <dd className="mt-1 font-mono text-kpi text-fg tabular-nums">{value}</dd>
          {context ? <dd className="mt-1.5 text-xs text-fg-secondary">{context}</dd> : null}
        </dl>
        {children}
      </CardContent>
    </Card>
  );
}
