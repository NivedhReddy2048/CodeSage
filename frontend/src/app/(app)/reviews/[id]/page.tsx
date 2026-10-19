"use client";

import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { PageHeader } from "@/components/page-header";
import { StatusBadge, reviewStatusKind } from "@/components/status-badge";
import { EmptyState, ErrorState, ListSkeleton } from "@/components/states";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api";
import { AGENT_LABELS, formatDuration, formatInr } from "@/lib/format";
import type { AgentRun, Review, ReviewFinding } from "@/lib/types";

function FindingRow({ finding }: { finding: ReviewFinding }) {
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge kind={finding.severity} />
        <code className="truncate text-sm font-medium">
          {finding.file_path}:{finding.line}
        </code>
        {finding.category ? (
          <span className="text-xs text-muted-foreground">{finding.category}</span>
        ) : null}
        <span className="text-xs text-muted-foreground">
          &middot; {AGENT_LABELS[finding.agent] ?? finding.agent}
        </span>
      </div>
      <p className="mt-1.5 text-sm">{finding.message}</p>
    </li>
  );
}

function agentKind(run: AgentRun) {
  if (run.skipped_reason) return "skipped" as const;
  return run.succeeded ? ("ok" as const) : ("failed" as const);
}

/** Short reason for everyone; the raw text only arrives for owners and admins. */
function ProblemNotice({ review }: { review: Review }) {
  if (!review.degraded && review.status !== "failed") return null;
  return (
    <ErrorState
      className="mb-6"
      title={review.degraded ? "Degraded mode: this change was not reviewed" : "Review failed"}
      message={`${review.error_summary || "The pipeline could not complete this review"}.`}
    />
  );
}

export default function ReviewPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params?.id);
  const resource = useResource(() => api.review(id), `review-${id}`);
  const review = resource.data;

  if (resource.loading) return <ListSkeleton rows={6} label="Loading review" />;
  if (resource.error || !review) {
    return (
      <ErrorState
        title={resource.status === 404 ? "Review not found" : "Could not load the review"}
        message={
          resource.status === 404
            ? "It does not exist, or it belongs to an organisation you are not viewing."
            : (resource.error ?? "Unknown error")
        }
        onRetry={resource.status === 404 ? undefined : resource.reload}
      />
    );
  }

  const blocking = review.findings.filter((f) => f.severity === "blocking");
  const nits = review.findings.filter((f) => f.severity !== "blocking");

  return (
    <>
      <PageHeader
        title={`${review.repository}#${review.pr_number}`}
        description={
          <>
            {review.pr_title || "Untitled"} &middot; <code>{review.head_sha.slice(0, 7)}</code>
          </>
        }
        actions={
          <>
            <StatusBadge kind={reviewStatusKind(review)} />
            {review.used_fallback ? <StatusBadge kind="fallback" /> : null}
            <a
              href={review.pr_url}
              target="_blank"
              rel="noreferrer"
              className={buttonVariants({ variant: "outline", size: "sm" })}
            >
              <ExternalLink aria-hidden="true" className="size-4" />
              View on GitHub
            </a>
          </>
        }
      />

      <ProblemNotice review={review} />

      {review.error && review.can_manage ? (
        <details className="mb-6 rounded-lg border px-4 py-3 text-sm">
          <summary className="cursor-pointer font-medium">Error details (owners and admins)</summary>
          <code className="mt-2 block text-xs break-all text-muted-foreground">{review.error}</code>
        </details>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>
              Findings <span className="text-muted-foreground">({review.findings.length})</span>
            </CardTitle>
            <CardDescription>
              {blocking.length} blocking, {nits.length} nit{nits.length === 1 ? "" : "s"}.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {review.findings.length === 0 ? (
              <EmptyState
                title={review.status === "done" ? "No issues found" : "No findings recorded"}
              />
            ) : (
              <ul className="divide-y">
                {[...blocking, ...nits].map((finding) => (
                  <FindingRow key={finding.id} finding={finding} />
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Cost and time</CardTitle>
              <CardDescription>Estimated at paid-tier rates; actual spend is zero.</CardDescription>
            </CardHeader>
            <CardContent>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                <dt className="text-muted-foreground">Duration</dt>
                <dd className="tabular-nums">{formatDuration(review.duration_ms)}</dd>
                <dt className="text-muted-foreground">Est. cost</dt>
                <dd className="tabular-nums">{formatInr(review.estimated_cost_inr, 4)}</dd>
                <dt className="text-muted-foreground">Tokens</dt>
                <dd className="tabular-nums">
                  {review.total_input_tokens} in / {review.total_output_tokens} out
                </dd>
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Agents</CardTitle>
            </CardHeader>
            <CardContent>
              {review.agent_runs.length === 0 ? (
                <EmptyState title="No agent runs recorded" />
              ) : (
                <ul className="space-y-2 text-sm">
                  {review.agent_runs.map((run) => (
                    <li key={run.id} className="flex items-center justify-between gap-2">
                      <span className="truncate">{AGENT_LABELS[run.name] ?? run.name}</span>
                      <StatusBadge kind={agentKind(run)} />
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      <p className="mt-6 text-sm">
        <Link href="/reviews" className="underline-offset-4 hover:underline">
          Back to all reviews
        </Link>
      </p>
    </>
  );
}
