"use client";

import { FolderGit2, GitPullRequest } from "lucide-react";
import Link from "next/link";

import { useOrganization } from "@/components/organization-provider";
import { PageHeader } from "@/components/page-header";
import { ReviewTable } from "@/components/review-table";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/states";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api";

/**
 * Dashboard. Phase 6d adds the KPI row and trend charts; this is the recent
 * activity they will sit above.
 */
export default function DashboardPage() {
  const { current } = useOrganization();
  const reviews = useResource(() => api.reviews({ page_size: 8 }), "recent-reviews");
  const repos = useResource(() => api.repositories(), "repositories");

  return (
    <>
      <PageHeader
        title="Dashboard"
        description={current ? `Recent review activity in ${current.name}.` : undefined}
        actions={
          <Link href="/reviews" className={buttonVariants({ variant: "outline" })}>
            All reviews
          </Link>
        }
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Recent reviews</CardTitle>
            <CardDescription>The latest pull requests CodeSage looked at.</CardDescription>
          </CardHeader>
          <CardContent>
            {reviews.loading ? (
              <TableSkeleton rows={5} columns={4} label="Loading reviews" />
            ) : reviews.error ? (
              <ErrorState message={reviews.error} onRetry={reviews.reload} />
            ) : reviews.data && reviews.data.results.length > 0 ? (
              <ReviewTable reviews={reviews.data.results} compact />
            ) : (
              <EmptyState
                icon={GitPullRequest}
                title="No reviews yet"
                description="Open a pull request on a connected repository and the review appears here."
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Repositories</CardTitle>
            <CardDescription>Connected to this organisation.</CardDescription>
          </CardHeader>
          <CardContent>
            {repos.loading ? (
              <TableSkeleton rows={3} columns={1} label="Loading repositories" />
            ) : repos.error ? (
              <ErrorState message={repos.error} onRetry={repos.reload} />
            ) : repos.data && repos.data.length > 0 ? (
              <ul className="space-y-2">
                {repos.data.map((repo) => (
                  <li key={repo.id} className="flex items-center gap-2 text-sm">
                    <FolderGit2 aria-hidden="true" className="size-4 text-muted-foreground" />
                    <Link
                      href={`/reviews?repository=${repo.id}`}
                      className="truncate underline-offset-4 hover:underline"
                    >
                      {repo.full_name}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                icon={FolderGit2}
                title="Nothing connected"
                action={
                  <Link href="/repos" className={buttonVariants({ size: "sm" })}>
                    Connect a repository
                  </Link>
                }
              />
            )}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
