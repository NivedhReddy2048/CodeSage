"use client";

import { Gauge } from "lucide-react";

import { Callout } from "@/components/states";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api";
import { DEMO_REVIEWS_PER_WORKSPACE, demoNote } from "@/lib/demo";
import type { DemoLimits } from "@/lib/types";
import { cn } from "@/lib/utils";

export function useDemoLimits() {
  return useResource<DemoLimits>(() => api.demoLimits(), "demo-limits");
}

/**
 * Shown across the app while a daily cap is reached. Loaded once per workspace (the
 * shell remounts its content on a switch), never polled: it is a notice, and a
 * poll would keep the database awake.
 */
export function DemoLimitBanner() {
  const { data } = useDemoLimits();
  if (!data?.reviews.limited) return null;
  const { workspace, global: everyone, scope } = data.reviews;
  const spent =
    scope === "workspace"
      ? `This workspace has used its ${workspace.limit} free reviews for today.`
      : `The demo's shared limit of ${everyone.limit} reviews for today is used up.`;
  return (
    <Callout tone="nit" icon={Gauge} role="status" title="Daily free-demo limit reached" className="mb-6">
      {spent} New pull requests get a comment saying so, and are reviewed automatically after the limit
      resets at 05:30 IST (00:00 UTC).
    </Callout>
  );
}

/** The dashboard's line under its title: the cap, and how much of it is used. */
export function DemoUsage({ className }: { className?: string }) {
  const { data } = useDemoLimits();
  const perWorkspace = data?.reviews.workspace.limit ?? DEMO_REVIEWS_PER_WORKSPACE;
  return (
    <p className={cn("inline-flex flex-wrap items-center gap-x-2 text-xs text-fg-secondary", className)}>
      <Gauge aria-hidden="true" className="size-3.5" />
      <span className="font-medium text-fg">{demoNote(perWorkspace)}</span>
      {data ? (
        <span>
          · {data.reviews.workspace.used} used today · public repositories only, up to{" "}
          {data.repositories.limit} per workspace
        </span>
      ) : null}
    </p>
  );
}
