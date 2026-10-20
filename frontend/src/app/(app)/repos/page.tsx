"use client";

import { Binary, Database, FileSearch, FolderGit2, GitBranch, Globe, Lock, Recycle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { IngestionStatus } from "@/components/ingestion-status";
import { useOrganization } from "@/components/organization-provider";
import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, ListSkeleton, errorMessage } from "@/components/states";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api";

const pill =
  "inline-flex items-center gap-1 rounded-md border bg-surface-2 px-1.5 py-0.5 text-[0.6875rem] font-medium text-fg-secondary";

/** Visibility and default branch, as pills. */
function RepoMeta({ privateRepo, branch }: { privateRepo: boolean; branch: string }) {
  return (
    <p className="mt-1.5 flex flex-wrap items-center gap-1.5">
      <span className={pill}>
        {privateRepo ? <Lock aria-hidden="true" className="size-3" /> : <Globe aria-hidden="true" className="size-3" />}
        {privateRepo ? "Private" : "Public"}
      </span>
      <span className={pill}>
        <GitBranch aria-hidden="true" className="size-3" />
        <span className="font-mono">{branch}</span>
      </span>
    </p>
  );
}

function OwnerRepo({ fullName }: { fullName: string }) {
  const [owner, name] = fullName.includes("/") ? fullName.split("/", 2) : ["", fullName];
  return (
    <span className="font-mono text-[0.8125rem]">
      {owner ? <span className="text-fg-secondary">{owner}/</span> : null}
      <span className="font-semibold text-fg">{name}</span>
    </span>
  );
}

/*
 * What indexing does, step by step, as backend/apps/ingestion does it. Each line is
 * a claim about that code - keep them in step with it.
 */
const INDEXING_STEPS = [
  {
    icon: FileSearch,
    title: "Read the default branch",
    body: "Source files only: generated, vendored, binary, oversized and .gitignored files are skipped.",
  },
  {
    icon: Binary,
    title: "Split into chunks",
    body: "Python by its AST, into functions, classes and their methods. Other languages split at declarations found by pattern.",
  },
  {
    icon: Database,
    title: "Embed and store",
    body: "Each chunk embedded with gemini-embedding-001 at 1536 dimensions into pgvector, with a Postgres full-text vector alongside.",
  },
  {
    icon: Recycle,
    title: "Reuse on re-index",
    body: "A chunk whose path and content hash are unchanged keeps its stored embedding instead of being embedded again.",
  },
];

function HowIndexingWorks() {
  return (
    <section aria-labelledby="indexing-heading" className="mt-6">
      <h2 id="indexing-heading" className="mb-3 text-h2 text-fg">
        How indexing works
      </h2>
      <ol className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {INDEXING_STEPS.map(({ icon: Icon, title, body }, index) => (
          <li key={title} className="rounded-xl border bg-surface-1 p-4 shadow-card">
            <div className="flex items-center gap-2">
              <span className="flex size-7 items-center justify-center rounded-lg border border-border-brand bg-brand-tinted text-brand">
                <Icon aria-hidden="true" className="size-3.5" />
              </span>
              <span className="font-mono text-xs text-fg-secondary">{String(index + 1).padStart(2, "0")}</span>
            </div>
            <p className="mt-3 text-sm font-semibold text-fg">{title}</p>
            <p className="mt-1 text-[0.8125rem] leading-[1.5] text-fg-secondary">{body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

export default function ReposPage() {
  const { canManage } = useOrganization();
  const connected = useResource(() => api.repositories(), "connected");
  const installable = useResource(() => api.installableRepositories(), "installable");

  const [actionError, setActionError] = useState<string | null>(null);
  // Per-repository, so one button spinning does not disable the others.
  const [busyId, setBusyId] = useState<number | null>(null);

  async function act(id: number, action: () => Promise<unknown>, failure: string, success: string) {
    setBusyId(id);
    setActionError(null);
    try {
      await action();
      connected.reload();
      installable.reload();
      toast.success(success);
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
        description="CodeSage reviews pull requests on connected repositories, grounded in each one's own index."
      />

      {actionError ? <ErrorState className="mb-6" message={actionError} /> : null}

      <section aria-labelledby="connected-heading">
        <h2 id="connected-heading" className="mb-3 text-h2 text-fg">
          Connected
          {connected.data ? (
            <span className="ml-2 rounded-full border bg-surface-1 px-1.5 font-mono text-xs font-normal text-fg-secondary tabular-nums">
              {connected.data.length}
            </span>
          ) : null}
        </h2>
        {connected.loading ? (
          <Card>
            <CardContent>
              <ListSkeleton rows={2} label="Loading repositories" />
            </CardContent>
          </Card>
        ) : connected.error ? (
          <ErrorState message={connected.error} onRetry={connected.reload} />
        ) : connected.data && connected.data.length > 0 ? (
          <ul className="grid gap-4 lg:grid-cols-2">
            {connected.data.map((repo) => (
              // A lone repository takes the full row rather than half of it.
              <li key={repo.id} className={connected.data?.length === 1 ? "lg:col-span-2" : undefined}>
                <Card className="h-full">
                  <CardContent>
                    <div className="flex items-start gap-3">
                      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-surface-2 text-fg-secondary">
                        <FolderGit2 aria-hidden="true" className="size-4" />
                      </span>
                      <div className="min-w-0 flex-1">
                        <Link
                          href={`/reviews?repository=${repo.id}`}
                          className="block truncate underline-offset-4 hover:underline"
                          title={`Reviews of ${repo.full_name}`}
                        >
                          <OwnerRepo fullName={repo.full_name} />
                        </Link>
                        <RepoMeta privateRepo={repo.private} branch={repo.default_branch} />
                      </div>
                      {canManage ? (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            void act(
                              repo.id,
                              () => api.disconnectRepository(repo.id),
                              "Could not disconnect.",
                              `Disconnected ${repo.full_name}`,
                            )
                          }
                          disabled={busyId === repo.id}
                        >
                          {busyId === repo.id ? "Removing..." : "Disconnect"}
                        </Button>
                      ) : null}
                    </div>
                    <IngestionStatus repositoryId={repo.id} />
                  </CardContent>
                </Card>
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
      </section>

      <Card className="mt-6">
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
                    <p className="truncate">
                      <OwnerRepo fullName={repo.full_name} />
                    </p>
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
                          `Connected ${repo.full_name}; indexing has started`,
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
            <p className="mt-4 text-xs text-fg-secondary">
              Connecting and disconnecting repositories needs the owner or admin role.
            </p>
          ) : null}
        </CardContent>
      </Card>

      <HowIndexingWorks />
    </>
  );
}
