"use client";

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

/** The reviews table shared by the dashboard and the reviews page. */
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
            <TableCell className="max-w-72">
              <Link
                href={`/reviews/${review.id}`}
                className="block truncate font-medium underline-offset-4 hover:underline"
              >
                {review.repository}#{review.pr_number}
              </Link>
              <span className="block truncate text-xs text-muted-foreground">
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
              <span className="tabular-nums">{review.finding_count}</span>
              {review.blocking_count ? (
                <span className="ml-1 text-xs text-status-blocking">
                  ({review.blocking_count} blocking)
                </span>
              ) : null}
            </TableCell>
            <TableCell className={`${wide} text-right tabular-nums`}>
              {review.status === "done" ? formatDuration(review.duration_ms) : "-"}
            </TableCell>
            <TableCell className={`${wide} text-right tabular-nums`}>
              {formatInr(review.estimated_cost_inr)}
            </TableCell>
            <TableCell className="hidden text-right text-muted-foreground sm:table-cell">
              <time dateTime={review.created_at}>{formatRelative(review.created_at)}</time>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
