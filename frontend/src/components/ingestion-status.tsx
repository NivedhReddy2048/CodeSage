"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { IngestionState } from "@/lib/types";

/** How often to re-check while a job is running. */
const POLL_INTERVAL_MS = 2500;

function describe(state: IngestionState): string {
  const { job, chunk_count, indexed_files } = state;

  if (!job) {
    return chunk_count > 0
      ? `${chunk_count} chunks indexed`
      : "Not indexed yet";
  }

  if (job.status === "pending") return "Queued for indexing...";

  if (job.status === "running") {
    // Files discovered is known early; indexed climbs as it works. Showing both
    // is more honest than a percentage that would jump around.
    return job.files_discovered
      ? `Indexing... ${job.files_indexed}/${job.files_discovered} files`
      : "Indexing...";
  }

  if (job.status === "failed") return "Indexing failed";

  const reused = job.chunks_reused
    ? `, ${job.chunks_reused} reused`
    : "";
  return `${chunk_count} chunks across ${indexed_files} files${reused}`;
}

function toneFor(state: IngestionState) {
  if (state.job?.status === "failed") return "text-destructive";
  if (state.job?.is_active) return "text-foreground";
  return "text-muted-foreground";
}

export function IngestionStatus({
  repositoryId,
  canManage,
}: {
  repositoryId: number;
  canManage: boolean;
}) {
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start indexing.");
    } finally {
      setStarting(false);
    }
  }

  const busy = starting || Boolean(state?.job?.is_active);

  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
      <p className={`text-sm ${state ? toneFor(state) : "text-muted-foreground"}`}>
        {state ? describe(state) : "Checking index..."}
      </p>

      {canManage ? (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => void reindex()}
          disabled={busy}
        >
          {busy ? "Indexing..." : "Re-index"}
        </Button>
      ) : null}

      {state?.job?.status === "failed" && state.job.error ? (
        <p className="w-full text-xs text-destructive">{state.job.error}</p>
      ) : null}

      {error ? <p className="w-full text-xs text-destructive">{error}</p> : null}
    </div>
  );
}
