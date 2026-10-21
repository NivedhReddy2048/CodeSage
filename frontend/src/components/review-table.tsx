"use client";

import { OctagonAlert } from "lucide-react";
import Link from "next/link";

import { Cost, ReviewRef } from "@/components/review-ref";
import { StatusBadge, reviewStatusKind } from "@/components/status-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDuration, formatRelative } from "@/lib/format";
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
              <ReviewRef sha={review.head_sha} trigger={review.trigger} className="mt-0.5" />
            </TableCell>
            <TableCell>
              <div className="flex flex-wrap gap-1">
                <StatusBadge kind={reviewStatusKind(review)} />
                {review.used_fallback ? <StatusBadge kind="fallback" /> : null}
              </div>
            </TableCell>
            <TableCell className="text-right">
              <FindingCounts blocking={review.blocking_count} nits={review.nit_count} />
            </TableCell>
            <TableCell className={`${wide} text-right font-mono tabular-nums`}>
              {review.status === "done" ? formatDuration(review.duration_ms) : "-"}
            </TableCell>
            <TableCell className={`${wide} text-right font-mono tabular-nums`}>
              <Cost value={review.estimated_cost_inr} />
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

/** "2 blocking · 1 nit" in words, blocking in its colour; "None" when clean. */
export function FindingCounts({ blocking, nits }: { blocking: number; nits: number }) {
  if (!blocking && !nits) return <span className="text-fg-secondary">None</span>;
  return (
    <span className="inline-flex items-center justify-end gap-1.5 text-xs whitespace-nowrap">
      {blocking ? (
        <span className="inline-flex items-center gap-1 font-medium text-status-blocking">
          <OctagonAlert aria-hidden="true" className="size-3" />
          <span className="tabular-nums">{blocking}</span> blocking
        </span>
      ) : null}
      {blocking && nits ? <span className="text-fg-secondary"> · </span> : null}
      {nits ? (
        <span className="text-fg-secondary">
          <span className="tabular-nums">{nits}</span> nit{nits === 1 ? "" : "s"}
        </span>
      ) : null}
    </span>
  );
}
