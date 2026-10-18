"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Button, buttonVariants } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { IngestionStatus } from "@/components/ingestion-status";
import { api } from "@/lib/api";
import type { ConnectedRepository, InstallableResponse } from "@/lib/types";

type PageData = {
  connected: ConnectedRepository[];
  installable: InstallableResponse;
};

async function loadRepositories(): Promise<PageData> {
  // Both in flight at once: neither depends on the other.
  const [connected, installable] = await Promise.all([
    api.repositories(),
    api.installableRepositories(),
  ]);
  return { connected, installable };
}

function RepoMeta({ privateRepo, branch }: { privateRepo: boolean; branch: string }) {
  return (
    <p className="truncate text-sm text-muted-foreground">
      {privateRepo ? "Private" : "Public"} &middot; {branch}
    </p>
  );
}

export default function ReposPage() {
  const router = useRouter();
  const { user, loading } = useAuth();

  const [data, setData] = useState<PageData | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Per-repository, so one button spinning does not disable the others.
  const [busyId, setBusyId] = useState<number | null>(null);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (!user) return;
    let active = true;

    loadRepositories()
      .then((next) => {
        if (active) setData(next);
      })
      .catch((err: unknown) => {
        if (active) {
          setError(
            err instanceof Error ? err.message : "Could not load repositories.",
          );
        }
      });

    return () => {
      active = false;
    };
  }, [user]);

  const refresh = useCallback(async () => {
    setData(await loadRepositories());
  }, []);

  async function connect(githubId: number) {
    setBusyId(githubId);
    setError(null);
    try {
      await api.connectRepository(githubId);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not connect.");
    } finally {
      setBusyId(null);
    }
  }

  async function disconnect(id: number) {
    setBusyId(id);
    setError(null);
    try {
      await api.disconnectRepository(id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not disconnect.");
    } finally {
      setBusyId(null);
    }
  }

  if (loading || !user) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-muted-foreground">Loading...</p>
      </div>
    );
  }

  const available = data?.installable.repositories.filter((r) => !r.connected) ?? [];

  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-12">
      <header className="mb-8 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Repositories</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            CodeSage reviews pull requests on connected repositories.
          </p>
        </div>
        <Link href="/" className={buttonVariants({ variant: "outline" })}>
          Back
        </Link>
      </header>

      {error ? (
        <p
          role="alert"
          className="mb-6 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
        >
          {error}
        </p>
      ) : null}

      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Connected</CardTitle>
          <CardDescription>
            Pull requests opened here are reviewed automatically.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {data === null ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : data.connected.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Nothing connected yet.
            </p>
          ) : (
            <ul className="divide-y">
              {data.connected.map((repo) => (
                <li
                  key={repo.id}
                  className="flex items-start justify-between gap-4 py-3 first:pt-0 last:pb-0"
                >
                  <div className="min-w-0">
                    <p className="truncate font-medium">{repo.full_name}</p>
                    <RepoMeta
                      privateRepo={repo.private}
                      branch={repo.default_branch}
                    />
                    <IngestionStatus repositoryId={repo.id} canManage />
                  </div>
                  <Button
                    variant="outline"
                    onClick={() => void disconnect(repo.id)}
                    disabled={busyId === repo.id}
                  >
                    {busyId === repo.id ? "Removing..." : "Disconnect"}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Available to connect</CardTitle>
          <CardDescription>
            Repositories the CodeSage GitHub App can access.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {data === null ? (
            <p className="text-sm text-muted-foreground">Loading...</p>
          ) : !data.installable.installed ? (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                The CodeSage GitHub App is not installed yet. Installing it is what
                grants access to a repository&apos;s pull requests.
              </p>
              {data.installable.install_url ? (
                <a
                  className={buttonVariants()}
                  href={data.installable.install_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Install the GitHub App
                </a>
              ) : null}
            </div>
          ) : available.length === 0 ? (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Everything the App can reach is already connected.
              </p>
              {data.installable.install_url ? (
                <a
                  className={buttonVariants({ variant: "outline" })}
                  href={data.installable.install_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Add more repositories on GitHub
                </a>
              ) : null}
            </div>
          ) : (
            <ul className="divide-y">
              {available.map((repo) => (
                <li
                  key={repo.github_id}
                  className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0"
                >
                  <div className="min-w-0">
                    <p className="truncate font-medium">{repo.full_name}</p>
                    <RepoMeta
                      privateRepo={repo.private}
                      branch={repo.default_branch}
                    />
                  </div>
                  <Button
                    onClick={() => void connect(repo.github_id)}
                    disabled={busyId === repo.github_id}
                  >
                    {busyId === repo.github_id ? "Connecting..." : "Connect"}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
