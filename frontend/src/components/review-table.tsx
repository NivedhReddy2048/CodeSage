"use client";

import { OctagonAlert } from "lucide-react";
import Link from "next/link";

import { StatusBadge, reviewStatusKind } from "@/components/status-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDuration, formatInr, formatRelative } from "@/lib/format";
import type { ReviewListItem } from "@/lib/types";

/**
 * The reviews table shared by the dashboard and the reviews page. Slugs, PR numbers
 * and every number are mono with tabular figures, so a column of costs or times
 * lines up digit for digit; numbers are right-aligned.
 */
export function ReviewTable({
  reviews,
  compact = false,
}: {
  reviews: ReviewListItem[];
  /** Drops time and cost, for narrow cards like the dashboard's. */
  compact?: boolean;
}) {
  const wide = compact ? "hidden" : "hidden md:table-cell";
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Pull request</TableHead>
          <TableHead>Status</TableHead>
          <TableHead className="text-right">Findings</TableHead>
          <TableHead className={`${wide} text-right`}>Time</TableHead>
          <TableHead className={`${wide} text-right`}>
            <abbr title="Estimated at paid-tier rates">Est. cost</abbr>
          </TableHead>
          <TableHead className="hidden text-right sm:table-cell">When</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {reviews.map((review) => (
          <TableRow key={review.id}>
            <TableCell className="max-w-80 py-2.5">
              <Link
                href={`/reviews/${review.id}`}
                className="block truncate font-mono text-[0.8125rem] font-medium text-fg underline-offset-4 hover:text-brand hover:underline"
              >
                {review.repository}#{review.pr_number}
              </Link>
              <span className="block truncate text-xs text-fg-secondary">
                {review.pr_title || "Untitled"}
              </span>
            </TableCell>
            <TableCell>
              <div className="flex flex-wrap gap-1">
                <StatusBadge kind={reviewStatusKind(review)} />
                {review.used_fallback ? <StatusBadge kind="fallback" /> : null}
              </div>
            </TableCell>
            <TableCell className="text-right">
              <span className="inline-flex items-center justify-end gap-1.5">
                {review.blocking_count ? (
                  <span
                    className="inline-flex h-5 items-center gap-1 rounded-full border border-status-blocking-border bg-status-blocking-bg px-1.5 text-[0.6875rem] font-medium text-status-blocking"
                    title={`${review.blocking_count} blocking`}
                  >
                    <OctagonAlert aria-hidden="true" className="size-3" />
                    <span className="font-mono tabular-nums">{review.blocking_count}</span>
                    <span className="sr-only"> blocking</span>
                  </span>
                ) : null}
                <span className="font-mono tabular-nums">{review.finding_count}</span>
              </span>
            </TableCell>
            <TableCell className={`${wide} text-right font-mono tabular-nums`}>
              {review.status === "done" ? formatDuration(review.duration_ms) : "-"}
            </TableCell>
            <TableCell className={`${wide} text-right font-mono tabular-nums`}>
              {formatInr(review.estimated_cost_inr)}
            </TableCell>
            <TableCell className="hidden text-right text-fg-secondary sm:table-cell">
              <time dateTime={review.created_at} className="font-mono text-xs tabular-nums">
                {formatRelative(review.created_at)}
              </time>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
