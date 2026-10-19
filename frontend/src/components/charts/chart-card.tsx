"use client";

import { Table2 } from "lucide-react";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export type LegendItem = { label: string; color: string };

/**
 * A chart's frame: title, one line of context, the legend (only for two or more
 * series - a single series is named by the title), and the table-view toggle that
 * is every chart's accessible twin. `stale` dims the previous render while a new
 * slice loads, instead of flashing a skeleton.
 */
export function ChartCard({
  title,
  description,
  legend,
  table,
  stale = false,
  className,
  children,
}: {
  title: string;
  description?: React.ReactNode;
  legend?: LegendItem[];
  table: React.ReactNode;
  stale?: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  const [showTable, setShowTable] = useState(false);
  const titleId = useId();

  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-start justify-between gap-3">
        <div className="min-w-0">
          <CardTitle id={titleId}>{title}</CardTitle>
          {description ? <CardDescription>{description}</CardDescription> : null}
        </div>
        <Button
          variant="ghost"
          size="sm"
          aria-pressed={showTable}
          onClick={() => setShowTable((value) => !value)}
        >
          <Table2 aria-hidden="true" className="size-4" />
          {showTable ? "Show chart" : "Show table"}
        </Button>
      </CardHeader>
      <CardContent>
        {legend && legend.length > 1 && !showTable ? (
          <ul aria-label="Legend" className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
            {legend.map((item) => (
              <li key={item.label} className="flex items-center gap-1.5">
                <span aria-hidden="true" className="size-2.5 rounded-[2px]" style={{ background: item.color }} />
                {item.label}
              </li>
            ))}
          </ul>
        ) : null}
        <figure
          aria-labelledby={titleId}
          className={cn("m-0 transition-opacity", stale && "opacity-50")}
          aria-busy={stale}
        >
          {showTable ? table : children}
        </figure>
      </CardContent>
    </Card>
  );
}

/** The plain-table view shared by every chart. */
export function DataTable({
  columns,
  rows,
}: {
  columns: { label: string; numeric?: boolean }[];
  rows: (string | number)[][];
}) {
  return (
    <div className="max-h-72 overflow-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-card">
          <tr className="border-b">
            {columns.map((column) => (
              <th
                key={column.label}
                scope="col"
                className={cn("py-1.5 pr-3 font-medium text-muted-foreground", column.numeric ? "text-right" : "text-left")}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} className="border-b last:border-0">
              {row.map((cell, cellIndex) => (
                <td
                  key={cellIndex}
                  className={cn("py-1.5 pr-3", columns[cellIndex]?.numeric && "text-right tabular-nums")}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
