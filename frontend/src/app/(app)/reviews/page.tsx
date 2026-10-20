"use client";

import { GitPullRequest } from "lucide-react";
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
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={id} className="text-micro text-fg-secondary">
        {label}
      </label>
      <NativeSelect id={id} value={value} onChange={(event) => onChange(event.target.value)}>
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
  const filtered = Boolean(filters.repository || filters.status || filters.severity);

  return (
    <>
      <PageHeader title="Reviews" description="Every pull request review in this organisation, newest first." />

      <Card>
        <CardContent>
          <form
            aria-label="Filter reviews"
            className="mb-4 grid gap-3 sm:grid-cols-[repeat(3,minmax(0,14rem))_auto] sm:items-end"
            onSubmit={(event) => event.preventDefault()}
          >
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
                onClick={() => update({ repository: "", status: "", severity: "" })}
              >
                Clear filters
              </Button>
            ) : null}
          </form>

          {reviews.loading ? (
            <TableSkeleton rows={8} columns={5} label="Loading reviews" />
          ) : reviews.error ? (
            <ErrorState message={reviews.error} onRetry={reviews.reload} />
          ) : reviews.data && reviews.data.results.length > 0 ? (
            <>
              <ReviewTable reviews={reviews.data.results} />
              <nav
                aria-label="Pagination"
                className="mt-4 flex items-center justify-between gap-2 text-sm text-muted-foreground"
              >
                <span>
                  Page {page} of {pages} &middot; {total} review{total === 1 ? "" : "s"}
                </span>
                <span className="flex gap-2">
                  <Button variant="outline" size="sm" disabled={!reviews.data.previous} onClick={() => update({ page: page - 1 })}>
                    Previous
                  </Button>
                  <Button variant="outline" size="sm" disabled={!reviews.data.next} onClick={() => update({ page: page + 1 })}>
                    Next
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
