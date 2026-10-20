"use client";

import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { StatusBadge, type StatusKind } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { IngestionState } from "@/lib/types";

/** How often to re-check while a job is running. */
const POLL_INTERVAL_MS = 2500;

/** The index's state as a badge: a word and an icon, never colour alone. */
function badgeFor(state: IngestionState | null): { kind: StatusKind; label: string } {
  if (!state) return { kind: "pending", label: "Checking index..." };
  const { job, chunk_count } = state;
  if (!job) return chunk_count > 0 ? { kind: "ok", label: "Indexed" } : { kind: "pending", label: "Not indexed yet" };
  if (job.status === "pending") return { kind: "pending", label: "Queued for indexing" };
  if (job.status === "running") {
    // Files discovered is known early; indexed climbs as it works. Showing both
    // is more honest than a percentage that would jump around.
    return {
      kind: "running",
      label: job.files_discovered ? `Indexing... ${job.files_indexed}/${job.files_discovered} files` : "Indexing...",
    };
  }
  if (job.status === "failed") return { kind: "failed", label: "Indexing failed" };
  return { kind: "ok", label: "Indexed" };
}

function Figure({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[0.6875rem] text-fg-secondary">{label}</dt>
      <dd className="truncate font-mono text-sm font-medium text-fg tabular-nums">{value}</dd>
    </div>
  );
}

/** A thin bar with its meaning in words beside it. */
function Meter({ value, max, label }: { value: number; max: number; label: React.ReactNode }) {
  const share = max > 0 ? Math.min(1, value / max) : 0;
  return (
    <div className="mt-3">
      <div aria-hidden="true" className="h-1.5 overflow-hidden rounded-full bg-[color:var(--chart-empty)]">
        <div className="h-full rounded-full bg-[color:var(--chart-primary)]" style={{ width: `${share * 100}%` }} />
      </div>
      <p className="mt-1.5 text-xs text-fg-secondary">{label}</p>
    </div>
  );
}

/**
 * A connected repository's index health: its state, how much is indexed, and how
 * much of the last run reused embeddings it already had (a chunk whose path and
 * content hash are unchanged is not embedded again). Polls only while a job runs.
 */
export function IngestionStatus({ repositoryId }: { repositoryId: number }) {
  const [state, setState] = useState<IngestionState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  // Held in a ref so the polling effect does not restart on every tick.
  const activeRef = useRef(false);

  const load = useCallback(async () => {
    const next = await api.ingestionStatus(repositoryId);
    activeRef.current = Boolean(next.job?.is_active);
    return next;
  }, [repositoryId]);

  useEffect(() => {
    let cancelled = false;

    load()
      .then((next) => {
        if (!cancelled) setState(next);
      })
      .catch(() => {
        // A status read failing is not worth shouting about; the row still
        // renders and the next poll may succeed.
      });

    return () => {
      cancelled = true;
    };
  }, [load]);

  // Poll only while something is actually happening, so a finished page stops
  // hitting the API.
  useEffect(() => {
    if (!state?.job?.is_active) return undefined;

    const timer = setInterval(() => {
      load()
        .then((next) => setState(next))
        .catch(() => undefined);
    }, POLL_INTERVAL_MS);

    return () => clearInterval(timer);
  }, [state?.job?.is_active, load]);

  async function reindex() {
    setStarting(true);
    setError(null);
    try {
      await api.reindexRepository(repositoryId);
      setState(await load());
      toast.success("Re-indexing started");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start indexing.");
    } finally {
      setStarting(false);
    }
  }

  const busy = starting || Boolean(state?.job?.is_active);
  // From the API, per repository: the role is checked server-side either way.
  const canManage = Boolean(state?.can_manage);
  const job = state?.job;
  const badge = badgeFor(state);

  return (
    <div className="mt-4 rounded-lg border bg-surface-2/50 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <StatusBadge kind={badge.kind} label={badge.label} />
        {canManage ? (
          <Button variant="ghost" size="sm" onClick={() => void reindex()} disabled={busy}>
            <RefreshCw aria-hidden="true" className="size-3.5" />
            {busy ? "Indexing..." : "Re-index"}
          </Button>
        ) : null}
      </div>

      {state ? (
        <dl className="mt-3 grid grid-cols-3 gap-3">
          <Figure label="Chunks" value={state.chunk_count} />
          <Figure label="Files" value={state.indexed_files} />
          <Figure label="Commit" value={job?.commit_sha ? job.commit_sha.slice(0, 7) : "-"} />
        </dl>
      ) : null}

      {job?.status === "running" && job.files_discovered ? (
        <Meter
          value={job.files_indexed}
          max={job.files_discovered}
          label={
            <>
              <span className="font-mono tabular-nums">{job.files_indexed}</span> of{" "}
              <span className="font-mono tabular-nums">{job.files_discovered}</span> files indexed
            </>
          }
        />
      ) : job?.status === "done" && job.chunks_created > 0 ? (
        <Meter
          value={job.chunks_reused}
          max={job.chunks_created}
          label={
            <>
              Last run reused <span className="font-mono tabular-nums">{job.chunks_reused}</span> of{" "}
              <span className="font-mono tabular-nums">{job.chunks_created}</span> chunk embeddings;{" "}
              <span className="font-mono tabular-nums">{job.embedding_api_calls}</span> embedding call
              {job.embedding_api_calls === 1 ? "" : "s"}
            </>
          }
        />
      ) : null}

      {job?.status === "failed" && job.error_summary ? (
        <div className="mt-3 text-xs text-status-blocking">
          {job.error_summary}.
          {/* Raw text is only sent to owners and admins; members get the reason. */}
          {job.error ? (
            <details className="mt-1">
              <summary className="cursor-pointer">Details</summary>
              <code className="mt-1 block font-mono break-all text-fg-secondary">{job.error}</code>
            </details>
          ) : null}
        </div>
      ) : null}

      {error ? (
        <p role="alert" className="mt-3 text-xs text-status-blocking">
          {error}
        </p>
      ) : null}
    </div>
  );
}
