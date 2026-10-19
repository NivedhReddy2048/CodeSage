"use client";

import { BarChart3, GitPullRequest } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { BarChart } from "@/components/charts/bar-chart";
import { ChartCard, DataTable, type LegendItem } from "@/components/charts/chart-card";
import { ColumnChart } from "@/components/charts/column-chart";
import { StatTile } from "@/components/charts/stat-tile";
import { useOrganization } from "@/components/organization-provider";
import { PageHeader } from "@/components/page-header";
import { ReviewTable } from "@/components/review-table";
import { EmptyState, ErrorState, ListSkeleton, TableSkeleton } from "@/components/states";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useResource } from "@/hooks/use-resource";
import { api, query } from "@/lib/api";
import { AGENT_LABELS, formatDuration, formatInr } from "@/lib/format";
import type { AnalyticsOverview } from "@/lib/types";
import { cn } from "@/lib/utils";

const PERIODS = [7, 30, 90] as const;

const SEVERITY_SERIES: LegendItem[] = [
  { label: "Blocking", color: "var(--series-1)" },
  { label: "Nits", color: "var(--series-2)" },
];

function shortDate(iso: string) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function Filters({
  days,
  repository,
  onChange,
}: {
  days: number;
  repository: string;
  onChange: (next: { days?: number; repository?: string }) => void;
}) {
  const repos = useResource(() => api.repositories(), "repositories");
  return (
    <div className="mb-6 flex flex-wrap items-end gap-4" role="group" aria-label="Dashboard filters">
      <fieldset>
        <legend className="mb-1 text-xs font-medium text-muted-foreground">Period</legend>
        <div className="inline-flex rounded-lg border p-0.5">
          {PERIODS.map((period) => (
            <label
              key={period}
              className={cn(
                "cursor-pointer rounded-md px-3 py-1 text-sm has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2",
                days === period ? "bg-muted font-medium" : "text-muted-foreground",
              )}
            >
              <input
                type="radio"
                name="period"
                className="sr-only"
                checked={days === period}
                onChange={() => onChange({ days: period })}
              />
              Last {period} days
            </label>
          ))}
        </div>
      </fieldset>
      <div className="flex flex-col gap-1">
        <label htmlFor="dashboard-repository" className="text-xs font-medium text-muted-foreground">
          Repository
        </label>
        <select
          id="dashboard-repository"
          value={repository}
          onChange={(event) => onChange({ repository: event.target.value })}
          className="h-8 rounded-md border bg-background px-2 text-sm"
        >
          <option value="">All repositories</option>
          {(repos.data ?? []).map((repo) => (
            <option key={repo.id} value={repo.id}>
              {repo.full_name}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

function Kpis({ data }: { data: AnalyticsOverview }) {
  const s = data.summary;
  return (
    <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatTile
        label="PRs reviewed"
        value={s.prs_reviewed}
        context={`${s.reviews} review${s.reviews === 1 ? "" : "s"} · ${s.degraded_reviews} degraded · ${s.failed_reviews} failed`}
      />
      <StatTile
        label="Avg findings per PR"
        value={s.avg_findings_per_pr ?? "-"}
        context={
          s.findings
            ? `${s.blocking} blocking, ${s.nits} nits (${Math.round((s.blocking_ratio ?? 0) * 100)}% blocking)`
            : "No findings in this period"
        }
      />
      <StatTile
        label="Avg review time"
        value={formatDuration(s.avg_latency_ms)}
        context="Completed reviews only"
      />
      <StatTile
        label="Est. cost per review"
        value={formatInr(s.est_cost_inr_avg, 2)}
        context={<span title={data.cost_basis}>At paid-tier rates · {formatInr(s.est_cost_inr_total, 2)} total; actual spend ₹0</span>}
      />
    </div>
  );
}

function Charts({ data, stale }: { data: AnalyticsOverview; stale: boolean }) {
  const perDay = data.timeseries.map((day) => ({
    key: day.date,
    label: shortDate(day.date),
    value: day.reviews,
  }));
  const categories = data.by_category.map((row) => ({
    key: row.key,
    label: row.key,
    values: [row.count],
  }));
  const agents = data.by_agent.map((row) => ({
    key: row.key,
    label: AGENT_LABELS[row.key] ?? row.key,
    values: [row.blocking, row.count - row.blocking],
  }));

  return (
    <div className="mb-6 grid gap-6 lg:grid-cols-2">
      <ChartCard
        className="lg:col-span-2"
        title="Reviews per day"
        description={`Every review started in the last ${data.range.days} days, including degraded and failed ones.`}
        stale={stale}
        table={
          <DataTable
            columns={[{ label: "Date" }, { label: "Reviews", numeric: true }, { label: "Findings", numeric: true }, { label: "Est. cost (₹)", numeric: true }]}
            rows={data.timeseries.map((day) => [day.date, day.reviews, day.findings, Number(day.est_cost_inr).toFixed(2)])}
          />
        }
      >
        <ColumnChart points={perDay} unit="reviews" />
      </ChartCard>

      <ChartCard
        title="Findings by category"
        description="Across completed reviews."
        stale={stale}
        table={
          <DataTable
            columns={[{ label: "Category" }, { label: "Findings", numeric: true }, { label: "Blocking", numeric: true }]}
            rows={data.by_category.map((row) => [row.key, row.count, row.blocking])}
          />
        }
      >
        {categories.length ? (
          <BarChart rows={categories} series={[{ label: "Findings", color: "var(--series-1)" }]} unit="findings" />
        ) : (
          <EmptyState icon={BarChart3} title="No findings in this period" />
        )}
      </ChartCard>

      <ChartCard
        title="Agent contribution"
        description="Findings each agent's wording was kept for after deduplication."
        legend={SEVERITY_SERIES}
        stale={stale}
        table={
          <DataTable
            columns={[{ label: "Agent" }, { label: "Blocking", numeric: true }, { label: "Nits", numeric: true }, { label: "Total", numeric: true }]}
            rows={data.by_agent.map((row) => [AGENT_LABELS[row.key] ?? row.key, row.blocking, row.count - row.blocking, row.count])}
          />
        }
      >
        {agents.length ? (
          <BarChart rows={agents} series={SEVERITY_SERIES} unit="findings" />
        ) : (
          <EmptyState icon={BarChart3} title="No findings in this period" />
        )}
      </ChartCard>
    </div>
  );
}

function Dashboard() {
  const router = useRouter();
  const params = useSearchParams();
  const { current } = useOrganization();
  const requested = Number(params.get("days"));
  const days = (PERIODS as readonly number[]).includes(requested) ? requested : 30;
  const repository = params.get("repository") ?? "";

  const filters = { days, repository };
  const analytics = useResource(() => api.analytics(filters), query(filters));
  const recent = useResource(
    () => api.reviews({ page_size: 6, repository }),
    `recent-${repository}`,
  );

  function update(next: { days?: number; repository?: string }) {
    const merged = { ...filters, ...next };
    router.push(`/${query({ days: merged.days === 30 ? undefined : merged.days, repository: merged.repository })}`);
  }

  return (
    <>
      <PageHeader
        title="Dashboard"
        description={current ? `Review activity in ${current.name}.` : undefined}
      />
      {/* One filter row, above everything it scopes. */}
      <Filters days={days} repository={repository} onChange={update} />

      {analytics.error ? (
        <ErrorState className="mb-6" message={analytics.error} onRetry={analytics.reload} />
      ) : !analytics.data ? (
        <div className="mb-6">
          <ListSkeleton rows={3} label="Loading analytics" />
        </div>
      ) : (
        <>
          <Kpis data={analytics.data} />
          {analytics.data.summary.reviews === 0 ? (
            <EmptyState
              className="mb-6"
              icon={GitPullRequest}
              title="No reviews in this period"
              description="Open a pull request on a connected repository, or widen the period."
            />
          ) : (
            <Charts data={analytics.data} stale={analytics.loading} />
          )}
        </>
      )}

      <Card>
        <CardHeader className="flex flex-row items-start justify-between gap-3">
          <div>
            <CardTitle>Recent reviews</CardTitle>
            <CardDescription>The latest pull requests CodeSage looked at.</CardDescription>
          </div>
          <Link href="/reviews" className={buttonVariants({ variant: "outline", size: "sm" })}>
            All reviews
          </Link>
        </CardHeader>
        <CardContent>
          {recent.loading && !recent.data ? (
            <TableSkeleton rows={4} columns={4} label="Loading reviews" />
          ) : recent.error ? (
            <ErrorState message={recent.error} onRetry={recent.reload} />
          ) : recent.data && recent.data.results.length > 0 ? (
            <ReviewTable reviews={recent.data.results} />
          ) : (
            <EmptyState icon={GitPullRequest} title="No reviews yet" />
          )}
        </CardContent>
      </Card>
    </>
  );
}

export default function DashboardPage() {
  return (
    <Suspense fallback={<ListSkeleton rows={4} label="Loading the dashboard" />}>
      <Dashboard />
    </Suspense>
  );
}
