"use client";

import { FolderGit2, Lock } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { IngestionStatus } from "@/components/ingestion-status";
import { useOrganization } from "@/components/organization-provider";
import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, ListSkeleton, errorMessage } from "@/components/states";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api";

function RepoMeta({ privateRepo, branch }: { privateRepo: boolean; branch: string }) {
  return (
    <p className="flex items-center gap-1 truncate text-sm text-muted-foreground">
      {privateRepo ? <Lock aria-hidden="true" className="size-3" /> : null}
      {privateRepo ? "Private" : "Public"} &middot; {branch}
    </p>
  );
}

export default function ReposPage() {
  const { canManage } = useOrganization();
  const connected = useResource(() => api.repositories(), "connected");
  const installable = useResource(() => api.installableRepositories(), "installable");

  const [actionError, setActionError] = useState<string | null>(null);
  // Per-repository, so one button spinning does not disable the others.
  const [busyId, setBusyId] = useState<number | null>(null);

  async function act(id: number, action: () => Promise<unknown>, failure: string) {
    setBusyId(id);
    setActionError(null);
    try {
      await action();
      connected.reload();
      installable.reload();
    } catch (err) {
      setActionError(errorMessage(err, failure));
    } finally {
      setBusyId(null);
    }
  }

  const available = installable.data?.repositories.filter((repo) => !repo.connected) ?? [];

  return (
    <>
      <PageHeader
        title="Repositories"
        description="CodeSage reviews pull requests on connected repositories."
      />

      {actionError ? <ErrorState className="mb-6" message={actionError} /> : null}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Connected</CardTitle>
            <CardDescription>Pull requests opened here are reviewed automatically.</CardDescription>
          </CardHeader>
          <CardContent>
            {connected.loading ? (
              <ListSkeleton rows={3} label="Loading repositories" />
            ) : connected.error ? (
              <ErrorState message={connected.error} onRetry={connected.reload} />
            ) : connected.data && connected.data.length > 0 ? (
              <ul className="divide-y">
                {connected.data.map((repo) => (
                  <li
                    key={repo.id}
                    className="flex flex-col gap-3 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-start sm:justify-between"
                  >
                    <div className="min-w-0">
                      <Link
                        href={`/reviews?repository=${repo.id}`}
                        className="truncate font-medium underline-offset-4 hover:underline"
                      >
                        {repo.full_name}
                      </Link>
                      <RepoMeta privateRepo={repo.private} branch={repo.default_branch} />
                      <IngestionStatus repositoryId={repo.id} />
                    </div>
                    {canManage ? (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() =>
                          void act(repo.id, () => api.disconnectRepository(repo.id), "Could not disconnect.")
                        }
                        disabled={busyId === repo.id}
                      >
                        {busyId === repo.id ? "Removing..." : "Disconnect"}
                      </Button>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                icon={FolderGit2}
                title="Nothing connected yet"
                description="Connect a repository from the list of ones the GitHub App can reach."
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Available to connect</CardTitle>
            <CardDescription>Repositories the CodeSage GitHub App can access.</CardDescription>
          </CardHeader>
          <CardContent>
            {installable.loading ? (
              <ListSkeleton rows={3} label="Loading available repositories" />
            ) : installable.error ? (
              <ErrorState message={installable.error} onRetry={installable.reload} />
            ) : !installable.data?.installed ? (
              <EmptyState
                title="The GitHub App is not installed"
                description="Installing it is what grants CodeSage access to a repository's pull requests."
                action={
                  installable.data?.install_url ? (
                    <a
                      className={buttonVariants({ size: "sm" })}
                      href={installable.data.install_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Install the GitHub App
                    </a>
                  ) : null
                }
              />
            ) : available.length === 0 ? (
              <EmptyState
                title="Everything is connected"
                description="Every repository the App can reach is already connected."
                action={
                  installable.data.install_url ? (
                    <a
                      className={buttonVariants({ variant: "outline", size: "sm" })}
                      href={installable.data.install_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Add repositories on GitHub
                    </a>
                  ) : null
                }
              />
            ) : (
              <ul className="divide-y">
                {available.map((repo) => (
                  <li
                    key={repo.github_id}
                    className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0"
                  >
                    <div className="min-w-0">
                      <p className="truncate font-medium">{repo.full_name}</p>
                      <RepoMeta privateRepo={repo.private} branch={repo.default_branch} />
                    </div>
                    {canManage ? (
                      <Button
                        size="sm"
                        onClick={() =>
                          void act(
                            repo.github_id,
                            () => api.connectRepository(repo.github_id),
                            "Could not connect.",
                          )
                        }
                        disabled={busyId === repo.github_id}
                      >
                        {busyId === repo.github_id ? "Connecting..." : "Connect"}
                      </Button>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
            {!canManage ? (
              <p className="mt-4 text-xs text-muted-foreground">
                Connecting and disconnecting repositories needs the owner or admin role.
              </p>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
