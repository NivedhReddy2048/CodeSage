"use client";

import { BarChart3, GitPullRequest, IndianRupee, ListChecks, Timer } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { BarChart } from "@/components/charts/bar-chart";
import { ChartCard, DataTable, type LegendItem } from "@/components/charts/chart-card";
import { ColumnChart } from "@/components/charts/column-chart";
import { BreakdownBar, Sparkline } from "@/components/charts/kpi-parts";
import { StatTile } from "@/components/charts/stat-tile";
import { useOrganization } from "@/components/organization-provider";
import { PageHeader } from "@/components/page-header";
import { ReviewTable } from "@/components/review-table";
import { EmptyState, ErrorState, ListSkeleton, TableSkeleton } from "@/components/states";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { useResource } from "@/hooks/use-resource";
import { api, query } from "@/lib/api";
import { AGENT_LABELS, formatDuration, formatInr } from "@/lib/format";
import type { AnalyticsOverview } from "@/lib/types";

const PERIODS = [7, 30, 90] as const;

const SEVERITY_SERIES: LegendItem[] = [
  { label: "Blocking", color: "var(--chart-blocking)" },
  { label: "Nits", color: "var(--chart-nit)" },
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
    // Part of the page header, above everything it scopes. Labels stay for assistive
    // tech; visually the options name themselves.
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Dashboard filters">
      <SegmentedControl
        legend="Period"
        hideLegend
        name="period"
        value={String(days)}
        options={PERIODS.map((period) => ({ value: String(period), label: `Last ${period} days` }))}
        onValueChange={(value) => onChange({ days: Number(value) })}
      />
      <label htmlFor="dashboard-repository" className="sr-only">
        Repository
      </label>
      <NativeSelect
        id="dashboard-repository"
        value={repository}
        onChange={(event) => onChange({ repository: event.target.value })}
        wrapperClassName="w-full sm:w-56"
        className="h-8"
      >
        <option value="">All repositories</option>
        {(repos.data ?? []).map((repo) => (
          <option key={repo.id} value={repo.id}>
            {repo.full_name}
          </option>
        ))}
      </NativeSelect>
    </div>
  );
}

function Kpis({ data }: { data: AnalyticsOverview }) {
  const s = data.summary;
  // Done, degraded and failed are disjoint (a degraded review is stored as failed
  // with the degraded flag; "failed" here excludes it). The rest are still running.
  const inProgress = Math.max(0, s.reviews - s.completed_reviews - s.degraded_reviews - s.failed_reviews);
  const latency = data.timeseries.map((day) => day.avg_latency_ms);
  const costPerReview = data.timeseries.map((day) => (day.reviews ? Number(day.est_cost_inr) / day.reviews : null));

  return (
    <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatTile
        icon={GitPullRequest}
        label="PRs reviewed"
        value={s.prs_reviewed}
        context={`${s.reviews} review${s.reviews === 1 ? "" : "s"} · ${s.degraded_reviews} degraded · ${s.failed_reviews} failed`}
      >
        <BreakdownBar
          segments={[
            { label: "done", value: s.completed_reviews, color: "var(--chart-primary)" },
            { label: "degraded", value: s.degraded_reviews, color: "var(--chart-nit)" },
            { label: "failed", value: s.failed_reviews, color: "var(--chart-blocking)" },
            { label: "in progress", value: inProgress, color: "var(--chart-secondary)" },
          ]}
        />
      </StatTile>
      <StatTile
        icon={ListChecks}
        label="Avg findings per PR"
        value={s.avg_findings_per_pr ?? "-"}
        context={
          s.findings
            ? `${s.blocking} blocking, ${s.nits} nits (${Math.round((s.blocking_ratio ?? 0) * 100)}% blocking)`
            : "No findings in this period"
        }
      >
        <BreakdownBar
          segments={[
            { label: "blocking", value: s.blocking, color: "var(--chart-blocking)" },
            { label: "nits", value: s.nits, color: "var(--chart-nit)" },
          ]}
        />
      </StatTile>
      <StatTile
        icon={Timer}
        label="Avg review time"
        value={formatDuration(s.avg_latency_ms)}
        context="Completed reviews only · daily average below"
      >
        <Sparkline values={latency} />
      </StatTile>
      <StatTile
        icon={IndianRupee}
        label="Est. cost per review"
        value={formatInr(s.est_cost_inr_avg, 2)}
        context={<span title={data.cost_basis}>At paid-tier rates · {formatInr(s.est_cost_inr_total, 2)} total; actual spend ₹0</span>}
      >
        <Sparkline values={costPerReview} color="var(--chart-secondary)" />
      </StatTile>
    </div>
  );
}

/** Four tile-shaped placeholders, so the page does not jump when the numbers land. */
function KpiSkeleton() {
  return (
    <div role="status" aria-label="Loading analytics" className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: 4 }, (_, index) => (
        <Card key={index} size="sm">
          <CardContent className="space-y-3">
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-8 w-2/5" />
            <Skeleton className="h-3 w-4/5" />
            <Skeleton className="h-1.5 w-full rounded-full" />
          </CardContent>
        </Card>
      ))}
      <span className="sr-only">Loading analytics...</span>
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
          <BarChart rows={categories} series={[{ label: "Findings", color: "var(--chart-primary)" }]} unit="findings" />
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
        actions={<Filters days={days} repository={repository} onChange={update} />}
      />

      {analytics.error ? (
        <ErrorState className="mb-6" message={analytics.error} onRetry={analytics.reload} />
      ) : !analytics.data ? (
        <KpiSkeleton />
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
