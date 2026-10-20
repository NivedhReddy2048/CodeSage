"use client";

import { ChevronLeft, ChevronRight, GitPullRequest, ListFilter, X } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { PageHeader } from "@/components/page-header";
import { ReviewTable } from "@/components/review-table";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { useResource } from "@/hooks/use-resource";
import { api, query } from "@/lib/api";

const PAGE_SIZE = 20;

const STATUSES = [
  { value: "", label: "Any status" },
  { value: "done", label: "Done" },
  { value: "running", label: "Running" },
  { value: "pending", label: "Pending" },
  { value: "degraded", label: "Degraded" },
  { value: "failed", label: "Failed" },
];

const SEVERITIES = [
  { value: "", label: "Any severity" },
  { value: "blocking", label: "Has blocking findings" },
  { value: "nit", label: "Has nits" },
];

function FilterSelect({
  id,
  label,
  value,
  options,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    // The label is for assistive tech; each select's first option names it visually
    // ("All repositories", "Any status"), and a set filter is outlined in brand.
    <div className="min-w-0 sm:w-52">
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <NativeSelect
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={value ? "border-brand bg-brand-tinted" : undefined}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </NativeSelect>
    </div>
  );
}

function ReviewsList() {
  const router = useRouter();
  const params = useSearchParams();
  const filters = {
    repository: params.get("repository") ?? "",
    status: params.get("status") ?? "",
    severity: params.get("severity") ?? "",
  };
  const page = Math.max(1, Number(params.get("page")) || 1);

  const request = { ...filters, page, page_size: PAGE_SIZE };
  const reviews = useResource(() => api.reviews(request), query(request));
  const repos = useResource(() => api.repositories(), "repositories");

  // Filters live in the URL, so a filtered view can be bookmarked and Back works.
  function update(next: Partial<typeof filters> & { page?: number }) {
    const merged = { ...filters, ...next };
    router.push(`/reviews${query({ ...merged, page: next.page && next.page > 1 ? next.page : undefined })}`);
  }

  const total = reviews.data?.count ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const active = [filters.repository, filters.status, filters.severity].filter(Boolean).length;
  const filtered = active > 0;

  return (
    <>
      <PageHeader title="Reviews" description="Every pull request review in this organisation, newest first." />

      <Card className="gap-0 py-0">
        {/* One toolbar on the table it filters. */}
        <form
          aria-label="Filter reviews"
          className="flex flex-col gap-2 border-b bg-surface-2/40 px-4 py-3 sm:flex-row sm:flex-wrap sm:items-center"
          onSubmit={(event) => event.preventDefault()}
        >
          <p className="flex items-center gap-2 text-sm font-medium text-fg sm:mr-1">
            <ListFilter aria-hidden="true" className="size-4 text-fg-secondary" />
            Filters
            {active ? (
              <span className="rounded-full border border-border-brand bg-brand-tinted px-1.5 font-mono text-xs text-brand tabular-nums">
                {active} active
              </span>
            ) : null}
          </p>
          <FilterSelect
            id="filter-repository"
            label="Repository"
            value={filters.repository}
            onChange={(repository) => update({ repository })}
            options={[
              { value: "", label: "All repositories" },
              ...(repos.data ?? []).map((repo) => ({ value: String(repo.id), label: repo.full_name })),
            ]}
          />
          <FilterSelect
            id="filter-status"
            label="Status"
            value={filters.status}
            options={STATUSES}
            onChange={(status) => update({ status })}
          />
          <FilterSelect
            id="filter-severity"
            label="Severity"
            value={filters.severity}
            options={SEVERITIES}
            onChange={(severity) => update({ severity })}
          />
          {filtered ? (
            <Button
              variant="ghost"
              size="sm"
              type="button"
              className="self-start sm:self-auto"
              onClick={() => update({ repository: "", status: "", severity: "" })}
            >
              <X aria-hidden="true" className="size-3.5" />
              Clear filters
            </Button>
          ) : null}
          {reviews.data ? (
            <span className="text-xs text-fg-secondary sm:ml-auto">
              <span className="font-mono tabular-nums">{total}</span> review{total === 1 ? "" : "s"}
            </span>
          ) : null}
        </form>

        <CardContent className="py-3">
          {reviews.loading ? (
            <TableSkeleton rows={8} columns={5} label="Loading reviews" />
          ) : reviews.error ? (
            <ErrorState message={reviews.error} onRetry={reviews.reload} />
          ) : reviews.data && reviews.data.results.length > 0 ? (
            <>
              <ReviewTable reviews={reviews.data.results} />
              <nav
                aria-label="Pagination"
                className="mt-3 flex items-center justify-between gap-2 border-t pt-3 text-sm text-fg-secondary"
              >
                <span>
                  Page <span className="font-mono text-fg tabular-nums">{page}</span> of{" "}
                  <span className="font-mono tabular-nums">{pages}</span> &middot;{" "}
                  <span className="font-mono tabular-nums">{total}</span> review{total === 1 ? "" : "s"}
                </span>
                <span className="flex gap-2">
                  <Button variant="outline" size="sm" disabled={!reviews.data.previous} onClick={() => update({ page: page - 1 })}>
                    <ChevronLeft aria-hidden="true" className="size-3.5" />
                    Previous
                  </Button>
                  <Button variant="outline" size="sm" disabled={!reviews.data.next} onClick={() => update({ page: page + 1 })}>
                    Next
                    <ChevronRight aria-hidden="true" className="size-3.5" />
                  </Button>
                </span>
              </nav>
            </>
          ) : (
            <EmptyState
              icon={GitPullRequest}
              title={filtered ? "No reviews match these filters" : "No reviews yet"}
              description={
                filtered
                  ? "Try clearing a filter."
                  : "Open a pull request on a connected repository and its review appears here."
              }
            />
          )}
        </CardContent>
      </Card>
    </>
  );
}

export default function ReviewsPage() {
  // useSearchParams needs a Suspense boundary for the static shell to prerender.
  return (
    <Suspense fallback={<TableSkeleton rows={8} columns={5} label="Loading reviews" />}>
      <ReviewsList />
    </Suspense>
  );
}
