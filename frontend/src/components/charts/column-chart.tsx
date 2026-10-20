"use client";

import { useState } from "react";

import { columnPath, compact, niceScale } from "@/components/charts/scale";
import { useElementWidth } from "@/hooks/use-element-width";

export type ColumnPoint = { key: string; label: string; value: number };

const PLOT_HEIGHT = 180;
const AXIS_BAND = 24; // x-axis labels live inside the frame, never under a scroll
const LEFT = 32;
const TOP = 16; // room for the peak label
const MAX_COLUMN = 24;
const AVERAGE_GUTTER = 64; // the average's label sits right of the plot, never on a column

/**
 * One series over time as thin columns: 4px rounded caps, square at the baseline,
 * <= 24px wide, hairline solid grid. The whole band under a column is its hit area,
 * and arrow keys walk the same readout for keyboard users. Only the peak is labelled;
 * the axis, tooltip and table view carry the rest.
 *
 * Sparse data: a day with nothing gets a faint full-height slot, so thirty days with
 * three reviews read as a calendar with three marks rather than a broken chart, and
 * a dashed line marks the period's daily average.
 */
export function ColumnChart({
  points,
  unit,
  formatValue = (value) => compact(value),
}: {
  points: ColumnPoint[];
  /** "reviews" - used in the tooltip and the accessible name. */
  unit: string;
  formatValue?: (value: number) => string;
}) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null);

  const average = points.length ? points.reduce((sum, p) => sum + p.value, 0) / points.length : 0;
  const showAverage = points.length > 1 && average > 0;
  const right = showAverage ? AVERAGE_GUTTER : 0;
  const plotWidth = Math.max(width - LEFT - right, 40);
  const { max, ticks } = niceScale(Math.max(0, ...points.map((p) => p.value)));
  const band = plotWidth / Math.max(points.length, 1);
  const column = Math.max(2, Math.min(MAX_COLUMN, band * 0.6));
  const y = (value: number) => TOP + PLOT_HEIGHT - (value / max) * PLOT_HEIGHT;
  const peak = points.reduce((best, p, i) => (p.value > (points[best]?.value ?? -1) ? i : best), 0);
  // About one date per 56px of plot, so a phone gets fewer labels, not overlapping
  // ones. The last day is labelled only when it has room after the previous label.
  const labelEvery = Math.max(1, Math.ceil(points.length / Math.max(2, Math.min(6, Math.floor(plotWidth / 56)))));
  const lastLabelled = (points.length - 1) % labelEvery >= labelEvery / 2 || (points.length - 1) % labelEvery === 0;
  const height = TOP + PLOT_HEIGHT + AXIS_BAND;

  function onKeyDown(event: React.KeyboardEvent) {
    if (!points.length) return;
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      event.preventDefault();
      const step = event.key === "ArrowRight" ? 1 : -1;
      setActive((current) =>
        Math.min(points.length - 1, Math.max(0, (current ?? points.length - 1) + (current === null ? 0 : step))),
      );
    } else if (event.key === "Escape") {
      setActive(null);
    }
  }

  const current = active !== null ? points[active] : null;

  return (
    <div
      ref={ref}
      className="relative w-full rounded-md outline-offset-4"
      tabIndex={0}
      role="group"
      aria-label={`${unit} per day; use the arrow keys to read each day`}
      onKeyDown={onKeyDown}
      onFocus={() => setActive((value) => value ?? points.length - 1)}
      onBlur={() => setActive(null)}
      onPointerLeave={() => setActive(null)}
    >
      <svg width={width} height={height} role="presentation" className="block overflow-visible">
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={LEFT}
              x2={LEFT + plotWidth}
              y1={y(tick)}
              y2={y(tick)}
              stroke={tick === 0 ? "var(--chart-axis)" : "var(--chart-grid)"}
              strokeWidth={1}
              shapeRendering="crispEdges"
            />
            <text x={LEFT - 6} y={y(tick)} dy="0.32em" textAnchor="end" className="fill-fg-secondary font-mono text-[10px] tabular-nums">
              {compact(tick)}
            </text>
          </g>
        ))}

        {points.map((point, index) => {
          const x = LEFT + index * band + (band - column) / 2;
          const top = y(point.value);
          return (
            <g key={point.key}>
              {point.value === 0 ? (
                <rect
                  data-empty-slot=""
                  x={x}
                  y={TOP}
                  width={column}
                  height={PLOT_HEIGHT}
                  rx={Math.min(4, column / 2)}
                  fill="var(--chart-empty)"
                />
              ) : null}
              <path
                d={columnPath(x, top, column, TOP + PLOT_HEIGHT - top)}
                fill="var(--chart-primary)"
                opacity={active === null || active === index ? 1 : 0.55}
              />
              {/* The hit area: the whole band, far bigger than the mark. */}
              <rect
                x={LEFT + index * band}
                y={TOP}
                width={band}
                height={PLOT_HEIGHT}
                fill="transparent"
                onPointerEnter={() => setActive(index)}
              />
              {index % labelEvery === 0 || (index === points.length - 1 && lastLabelled) ? (
                <text
                  x={LEFT + index * band + band / 2}
                  y={TOP + PLOT_HEIGHT + 16}
                  textAnchor="middle"
                  className="fill-fg-secondary text-[10px]"
                >
                  {point.label}
                </text>
              ) : null}
              {index === peak && point.value > 0 ? (
                <text
                  x={x + column / 2}
                  y={top - 5}
                  textAnchor="middle"
                  className="fill-foreground text-[11px] font-medium"
                >
                  {formatValue(point.value)}
                </text>
              ) : null}
            </g>
          );
        })}

        {showAverage ? (
          <g data-average="">
            <line
              x1={LEFT}
              x2={LEFT + plotWidth + 4}
              y1={y(average)}
              y2={y(average)}
              stroke="var(--text-secondary)"
              strokeWidth={1}
              strokeDasharray="4 4"
              shapeRendering="crispEdges"
            />
            <text
              x={LEFT + plotWidth + 8}
              y={y(average)}
              dy="0.32em"
              className="fill-fg-secondary font-mono text-[10px] tabular-nums"
            >
              <tspan>avg</tspan>
              <tspan x={LEFT + plotWidth + 8} dy="1.2em">
                {formatValue(Number(average.toFixed(1)))}/day
              </tspan>
            </text>
          </g>
        ) : null}
      </svg>

      {current ? (
        <div
          role="status"
          className="pointer-events-none absolute z-10 rounded-md border bg-popover px-2.5 py-1.5 text-xs shadow-popover"
          style={{
            left: Math.min(Math.max(LEFT + (active ?? 0) * band + band / 2 - 60, 0), width - 120),
            top: 0,
            width: 120,
          }}
        >
          <span className="block font-mono text-sm font-semibold tabular-nums">
            {formatValue(current.value)} {unit}
          </span>
          <span className="flex items-center gap-1.5 text-fg-secondary">
            <span aria-hidden="true" className="h-0.5 w-3 rounded" style={{ background: "var(--chart-primary)" }} />
            {current.label}
          </span>
        </div>
      ) : null}
    </div>
  );
}
