"use client";

import { useState } from "react";

import type { LegendItem } from "@/components/charts/chart-card";
import { compact, niceScale } from "@/components/charts/scale";

export type BarRow = { key: string; label: string; values: number[] };

const THICKNESS = 16; // <= 24px: thin marks, the rest of the row is air

/**
 * Horizontal bars, one series or two stacked. Labels are text tokens; colour is only
 * on the marks. Stacked segments are separated by a 2px surface gap, not a stroke;
 * only the data end is rounded. Each row is focusable and its readout lists every
 * series, so hover and keyboard show the same thing.
 */
export function BarChart({
  rows,
  series,
  unit,
}: {
  rows: BarRow[];
  /** One entry per value in a row, in stacking order. */
  series: LegendItem[];
  unit: string;
}) {
  const [active, setActive] = useState<string | null>(null);
  const totals = rows.map((row) => row.values.reduce((sum, value) => sum + value, 0));
  const { max } = niceScale(Math.max(0, ...totals));

  return (
    <ul className="space-y-2.5" aria-label={`${unit} by ${series.length > 1 ? "category and series" : "category"}`}>
      {rows.map((row, rowIndex) => {
        const total = totals[rowIndex];
        const segments = row.values
          .map((value, index) => ({ value, index }))
          .filter((segment) => segment.value > 0);
        const readout = series
          .map((item, index) => `${row.values[index] ?? 0} ${item.label.toLowerCase()}`)
          .join(", ");

        return (
          <li
            key={row.key}
            tabIndex={0}
            aria-label={`${row.label}: ${total} ${unit}${series.length > 1 ? ` (${readout})` : ""}`}
            className="relative grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)] items-center gap-3 rounded-md text-sm outline-offset-2"
            onPointerEnter={() => setActive(row.key)}
            onPointerLeave={() => setActive(null)}
            onFocus={() => setActive(row.key)}
            onBlur={() => setActive(null)}
          >
            <span className="truncate text-muted-foreground" title={row.label}>
              {row.label}
            </span>
            <span className="flex items-center gap-2">
              <span
                className="flex"
                style={{ width: `${(total / max) * 100}%`, height: THICKNESS }}
                aria-hidden="true"
              >
                {segments.map((segment, position) => (
                  <span
                    key={segment.index}
                    className={position === segments.length - 1 ? "rounded-r-[4px]" : ""}
                    style={{
                      flexGrow: segment.value,
                      flexBasis: 0,
                      background: series[segment.index]?.color,
                      // The 2px surface gap between stacked segments.
                      marginLeft: position === 0 ? 0 : 2,
                      opacity: active === null || active === row.key ? 1 : 0.55,
                    }}
                  />
                ))}
              </span>
              <span className="shrink-0 text-xs font-medium tabular-nums">{compact(total)}</span>
            </span>

            {active === row.key && series.length > 1 ? (
              <span
                role="status"
                className="pointer-events-none absolute right-0 bottom-full z-10 mb-1 rounded-md border bg-popover px-2.5 py-1.5 text-xs shadow-md"
              >
                <span className="mb-0.5 block font-medium text-muted-foreground">{row.label}</span>
                {series.map((item, index) => (
                  <span key={item.label} className="flex items-center gap-1.5">
                    <span aria-hidden="true" className="h-0.5 w-3 rounded" style={{ background: item.color }} />
                    <span className="font-semibold tabular-nums">{row.values[index] ?? 0}</span>
                    <span className="text-muted-foreground">{item.label}</span>
                  </span>
                ))}
              </span>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
