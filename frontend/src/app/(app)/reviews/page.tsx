"use client";

import { GitPullRequest } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { PageHeader } from "@/components/page-header";
import { ReviewTable } from "@/components/review-table";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { useResource } from "@/hooks/use-resource";
import { api, query } from "@/lib/api";

const PAGE_SIZE = 20;

function ReviewsList() {
  const router = useRouter();
  const params = useSearchParams();
  const repository = params.get("repository") ?? "";
  const page = Math.max(1, Number(params.get("page")) || 1);

  const filters = { repository, page, page_size: PAGE_SIZE };
  const reviews = useResource(() => api.reviews(filters), query(filters));

  function goTo(nextPage: number) {
    router.push(`/reviews${query({ repository, page: nextPage > 1 ? nextPage : undefined })}`);
  }

  const total = reviews.data?.count ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <>
      <PageHeader
        title="Reviews"
        description="Every pull request review in this organisation, newest first."
      />
      <Card>
        <CardContent>
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
                  <Button variant="outline" size="sm" disabled={!reviews.data.previous} onClick={() => goTo(page - 1)}>
                    Previous
                  </Button>
                  <Button variant="outline" size="sm" disabled={!reviews.data.next} onClick={() => goTo(page + 1)}>
                    Next
                  </Button>
                </span>
              </nav>
            </>
          ) : (
            <EmptyState
              icon={GitPullRequest}
              title="No reviews"
              description={
                repository
                  ? "This repository has no reviews yet."
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
