"use client";

import { ArrowLeft, CircleX, ExternalLink, GitCommitHorizontal, GitPullRequest, Scissors, Shuffle, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo } from "react";

import { useOrganization } from "@/components/organization-provider";
import { AgentProgress } from "@/components/review/agent-progress";
import { AgentsTable } from "@/components/review/agents-table";
import { DiffViewer, unanchoredFindings } from "@/components/review/diff-viewer";
import { FindingsPanel } from "@/components/review/findings-panel";
import { RerunButton } from "@/components/review/rerun-button";
import { ReviewStatusPill } from "@/components/review/status-pill";
import { StatusBadge } from "@/components/status-badge";
import { Callout, EmptyState, ErrorState, ListSkeleton, TableSkeleton } from "@/components/states";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useResource } from "@/hooks/use-resource";
import { useReviewProgress } from "@/hooks/use-review-progress";
import { api } from "@/lib/api";
import { formatDuration, formatInr } from "@/lib/format";
import type { Review } from "@/lib/types";

function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="min-w-0 px-4 py-3">
      <dt className="text-micro text-fg-secondary">{label}</dt>
      <dd className="mt-1 truncate font-mono text-lg font-semibold text-fg tabular-nums" title={hint}>
        {value}
      </dd>
    </div>
  );
}

function Summary({ review, inFlight }: { review: Review; inFlight: boolean }) {
  const blocking = review.findings.filter((f) => f.severity === "blocking").length;
  // While agents run nothing is final; dashes, not zeros that read as results.
  const pending = (value: React.ReactNode) => (inFlight ? "-" : value);
  return (
    <Card className="mb-6 py-0">
      <dl className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 lg:divide-x">
        <Stat
          label="Findings"
          value={pending(
            <>
              {review.findings.length}
              {blocking ? (
                <span className="ml-1.5 font-sans text-sm font-medium text-status-blocking">{blocking} blocking</span>
              ) : null}
            </>,
          )}
        />
        <Stat label="Review time" value={review.status === "done" ? formatDuration(review.duration_ms) : "-"} />
        <Stat
          label="Est. cost at paid-tier rates"
          value={pending(formatInr(review.estimated_cost_inr, 4))}
          hint="CodeSage runs on free tiers; actual spend is zero."
        />
        <Stat
          label="Tokens (in / out)"
          value={pending(`${review.total_input_tokens} / ${review.total_output_tokens}`)}
        />
        <Stat
          label={review.used_fallback ? "Models (fallback)" : "Models"}
          value={pending(<span className="text-sm font-medium">{review.model_used || "-"}</span>)}
          hint={review.model_used}
        />
      </dl>
    </Card>
  );
}

/** What a reader must know before trusting the page, each as one structured callout. */
function Notices({ review }: { review: Review }) {
  return (
    <div className="mb-4 space-y-3 empty:hidden">
      {review.degraded ? (
        <Callout tone="nit" icon={TriangleAlert} role="alert" title="Degraded mode: this change was not reviewed">
          {review.error_summary || "No language model answered"}. Local static analysis ran, but no
          model-backed agent could read the change, so nothing here is an approval.
        </Callout>
      ) : review.status === "failed" ? (
        <Callout tone="blocking" icon={CircleX} role="alert" title="Review failed">
          {review.error_summary || "The pipeline could not complete this review"}.
        </Callout>
      ) : null}
      {review.used_fallback && !review.degraded ? (
        <Callout tone="info" icon={Shuffle} title="Answered by the fallback provider">
          The primary provider did not answer for at least one agent, so the fallback served it.
          The agents table shows which, and the model that was asked for.
        </Callout>
      ) : null}
      {review.truncated || review.skipped_files.length > 0 ? (
        <Callout tone="nit" icon={Scissors} title="Not every line was reviewed">
          {review.truncated ? <p>The diff exceeded the review budget, so only part of it was read.</p> : null}
          {review.skipped_files.length ? (
            <p>
              Skipped as generated, binary or too large:{" "}
              <span className="font-mono text-xs">{review.skipped_files.slice(0, 8).join(", ")}</span>
              {review.skipped_files.length > 8 ? ` and ${review.skipped_files.length - 8} more` : ""}
            </p>
          ) : null}
        </Callout>
      ) : null}
      {review.error && review.can_manage ? (
        <details className="rounded-xl border bg-surface-1 px-4 py-3 text-sm">
          <summary className="cursor-pointer font-medium text-fg">Error details (owners and admins)</summary>
          <code className="mt-2 block font-mono text-xs break-all text-fg-secondary">{review.error}</code>
        </details>
      ) : null}
    </div>
  );
}

/** The repository and PR as a badge, the commit reviewed, then the PR's own title. */
function ReviewHeader({ review, actions }: { review: Review; actions: React.ReactNode }) {
  return (
    <header className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
      <div className="min-w-0">
        <p className="mb-2 flex flex-wrap items-center gap-2 text-xs text-fg-secondary">
          <span className="inline-flex min-w-0 items-center gap-1.5 rounded-md border bg-surface-1 px-2 py-0.5 font-mono">
            <GitPullRequest aria-hidden="true" className="size-3.5 shrink-0 text-brand" />
            <span className="truncate">{review.repository}</span>
            <span className="text-fg">#{review.pr_number}</span>
          </span>
          <span className="inline-flex items-center gap-1 font-mono" title="The commit this review read">
            <GitCommitHorizontal aria-hidden="true" className="size-3.5" />
            <span className="sr-only">Reviewed at commit </span>
            {review.head_sha.slice(0, 7)}
          </span>
        </p>
        <h1 className="font-mono text-h1 [overflow-wrap:anywhere] text-fg">
          {review.repository}#{review.pr_number}
        </h1>
        <p className="mt-1 text-body text-fg-secondary">{review.pr_title || "Untitled"}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2 lg:max-w-[55%] lg:justify-end">{actions}</div>
    </header>
  );
}

export default function ReviewPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params?.id);
  const { canManage } = useOrganization();

  const reviewResource = useResource(() => api.review(id), `review-${id}`);
  const diffResource = useResource(() => api.reviewDiff(id), `diff-${id}`);
  const review = reviewResource.data;

  const live = useReviewProgress(id, review?.status, () => {
    reviewResource.reload();
    diffResource.reload();
  });

  const liveStatus = live.progress?.status ?? review?.status ?? "";
  const inFlight = liveStatus === "pending" || liveStatus === "running";

  const unanchored = useMemo(
    () => (review && diffResource.data ? unanchoredFindings(diffResource.data.diff, review.findings) : []),
    [review, diffResource.data],
  );

  if (reviewResource.loading && !review) return <ListSkeleton rows={6} label="Loading review" />;
  if (reviewResource.error || !review) {
    const missing = reviewResource.status === 404;
    return (
      <ErrorState
        title={missing ? "Review not found" : "Could not load the review"}
        message={
          missing
            ? "It does not exist, or it belongs to an organisation you are not viewing."
            : (reviewResource.error ?? "Unknown error")
        }
        onRetry={missing ? undefined : reviewResource.reload}
      />
    );
  }

  return (
    <>
      <ReviewHeader
        review={review}
        actions={
          <>
            <ReviewStatusPill
              status={review.status}
              degraded={review.degraded}
              stalled={review.stalled}
              progress={live.progress}
              transport={live.transport}
            />
            {review.used_fallback ? <StatusBadge kind="fallback" /> : null}
            {canManage && review.can_manage ? (
              <RerunButton reviewId={review.id} pullRequest={`${review.repository}#${review.pr_number}`} />
            ) : null}
            <a
              href={review.pr_url}
              target="_blank"
              rel="noreferrer"
              className={buttonVariants({ variant: "outline", size: "sm" })}
            >
              <ExternalLink aria-hidden="true" className="size-4" />
              Pull request on GitHub
            </a>
          </>
        }
      />

      {inFlight ? (
        <Card className="mb-6">
          <CardContent>
            <AgentProgress agents={live.progress?.agents ?? review.progress} />
          </CardContent>
        </Card>
      ) : null}
      <Notices review={review} />
      <Summary review={review} inFlight={inFlight} />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <section aria-labelledby="diff-heading" className="min-w-0">
          <h2 id="diff-heading" className="mb-3 text-h2 text-fg">
            Changes, with findings on their lines
          </h2>
          {diffResource.loading && !diffResource.data ? (
            <TableSkeleton rows={10} columns={1} label="Loading the diff" />
          ) : diffResource.error ? (
            <ErrorState
              title="The diff is unavailable"
              message={`${diffResource.error} The findings are still listed alongside.`}
              onRetry={diffResource.reload}
            />
          ) : diffResource.data ? (
            <>
              {diffResource.data.truncated ? (
                <p className="mb-3 text-xs text-fg-secondary">
                  This diff is very large; only the first part is shown.
                </p>
              ) : null}
              <DiffViewer diff={diffResource.data.diff} findings={review.findings} />
            </>
          ) : (
            <EmptyState title="No diff to show" />
          )}
        </section>

        <aside aria-labelledby="findings-heading" className="lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:self-start lg:overflow-y-auto">
          <h2 id="findings-heading" className="mb-3 text-h2 text-fg">
            Findings
          </h2>
          <FindingsPanel findings={review.findings} unanchored={unanchored} status={liveStatus} />
        </aside>
      </div>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Agents</CardTitle>
          <CardDescription>
            The model that actually served each agent. After a failover it is the fallback&apos;s, with
            the model that was asked for underneath.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {review.agent_runs.length ? (
            <AgentsTable runs={review.agent_runs} />
          ) : (
            <EmptyState
              title={inFlight ? "Agents are still running" : "No agent runs recorded"}
            />
          )}
        </CardContent>
      </Card>

      <p className="mt-6 text-sm">
        <Link
          href="/reviews"
          className="inline-flex items-center gap-1.5 text-fg-secondary underline-offset-4 hover:text-fg hover:underline"
        >
          <ArrowLeft aria-hidden="true" className="size-4" />
          Back to all reviews
        </Link>
      </p>
    </>
  );
}
