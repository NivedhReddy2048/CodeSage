"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { api } from "@/lib/api";
import type { Review, ReviewFinding } from "@/lib/types";

/**
 * Phase 4 review view: prove the loop end to end.
 *
 * The split diff pane with threaded per-line comments is phase 6 (spec section 9).
 * This page deliberately stops at a findings list plus the telemetry, which is what
 * the phase 4 prompt asks for.
 */

function severityClass(severity: string) {
  return severity === "blocking"
    ? "border-destructive/40 bg-destructive/10 text-destructive"
    : "border-border bg-muted text-muted-foreground";
}

function FindingRow({ finding }: { finding: ReviewFinding }) {
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`rounded-full border px-2 py-0.5 text-xs capitalize ${severityClass(
            finding.severity,
          )}`}
        >
          {finding.severity}
        </span>
        <code className="truncate text-sm font-medium">
          {finding.file_path}:{finding.line}
        </code>
        {finding.category ? (
          <span className="text-xs text-muted-foreground">{finding.category}</span>
        ) : null}
      </div>
      <p className="mt-1.5 text-sm">{finding.message}</p>
    </li>
  );
}

export default function ReviewPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const { user, loading } = useAuth();

  const [review, setReview] = useState<Review | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (!user || !params?.id) return;
    let active = true;

    api
      .review(Number(params.id))
      .then((next) => {
        if (active) setReview(next);
      })
      .catch((err: unknown) => {
        if (active) {
          setError(err instanceof Error ? err.message : "Could not load the review.");
        }
      });

    return () => {
      active = false;
    };
  }, [user, params?.id]);

  if (loading || !user) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto w-full max-w-2xl px-4 py-12">
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
        <Link href="/repos" className={buttonVariants({ className: "mt-6" })}>
          Back to repositories
        </Link>
      </div>
    );
  }

  if (!review) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading review...</p>
      </div>
    );
  }

  const blocking = review.findings.filter((f) => f.severity === "blocking");
  const nits = review.findings.filter((f) => f.severity !== "blocking");
  const seconds = (review.duration_ms / 1000).toFixed(1);

  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-12">
      <header className="mb-8 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="truncate text-xl font-semibold tracking-tight">
            {review.repository} #{review.pr_number}
          </h1>
          <p className="mt-1 truncate text-sm text-muted-foreground">
            {review.pr_title || "Untitled"} &middot;{" "}
            <code>{review.head_sha.slice(0, 7)}</code>
          </p>
        </div>
        <Link href="/repos" className={buttonVariants({ variant: "outline" })}>
          Back
        </Link>
      </header>

      {review.status === "failed" ? (
        <Card className="mb-6 border-destructive/40">
          <CardHeader>
            <CardTitle>Review failed</CardTitle>
            <CardDescription>
              The pipeline could not complete this review.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-destructive">{review.error}</p>
          </CardContent>
        </Card>
      ) : null}

      {review.truncated || review.skipped_files.length > 0 ? (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle>Not fully reviewed</CardTitle>
            <CardDescription>
              A short review of a partial diff should not read as a clean bill of
              health.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm text-muted-foreground">
            {review.truncated ? (
              <p>The diff exceeded the review budget, so only part of it was read.</p>
            ) : null}
            {review.skipped_files.length > 0 ? (
              <p>
                Skipped as generated, binary or too large:{" "}
                {review.skipped_files.slice(0, 10).join(", ")}
                {review.skipped_files.length > 10
                  ? ` and ${review.skipped_files.length - 10} more`
                  : ""}
              </p>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      <Card className="mb-6">
        <CardHeader>
          <CardTitle>
            Findings{" "}
            <span className="text-muted-foreground">({review.findings.length})</span>
          </CardTitle>
          <CardDescription>
            {blocking.length} blocking, {nits.length} nit
            {nits.length === 1 ? "" : "s"}.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {review.findings.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {review.status === "done"
                ? "No issues found."
                : "No findings recorded."}
            </p>
          ) : (
            <ul className="divide-y">
              {[...blocking, ...nits].map((finding) => (
                <FindingRow key={finding.id} finding={finding} />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Cost and latency</CardTitle>
          <CardDescription>
            An estimate at paid-tier rates. This project runs on free tiers, so actual
            spend is zero.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Duration</dt>
            <dd>{seconds} s</dd>
            <dt className="text-muted-foreground">Model</dt>
            <dd className="truncate">
              {review.model_used || "-"}
              {review.used_fallback ? " (fallback)" : ""}
            </dd>
            <dt className="text-muted-foreground">Tokens</dt>
            <dd>
              {review.total_input_tokens} in / {review.total_output_tokens} out
            </dd>
            <dt className="text-muted-foreground">Est. cost</dt>
            <dd>&#8377;{Number(review.estimated_cost_inr).toFixed(4)}</dd>
          </dl>

          {review.calls.length > 0 ? (
            <ul className="mt-4 space-y-1 border-t pt-3 text-xs text-muted-foreground">
              {review.calls.map((call) => (
                <li key={call.id} className="truncate">
                  {call.provider}/{call.model} &middot; {call.input_tokens}+
                  {call.output_tokens} tok &middot; {call.latency_ms} ms &middot;{" "}
                  {call.succeeded ? "ok" : `failed: ${call.error.slice(0, 60)}`}
                  {call.is_fallback ? " (fallback)" : ""}
                </li>
              ))}
            </ul>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
