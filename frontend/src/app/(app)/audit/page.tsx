"use client";

import {
  ChevronLeft,
  ChevronRight,
  Lock,
  LogIn,
  LogOut,
  PlugZap,
  RefreshCw,
  RotateCw,
  ScrollText,
  ShieldAlert,
  Unplug,
  UserCog,
  type LucideIcon,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useResource } from "@/hooks/use-resource";
import { api, query } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { AuditEntry } from "@/lib/types";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

export const AUDIT_ACTIONS = [
  { value: "", label: "Any action" },
  { value: "repo.connected", label: "Repository connected" },
  { value: "repo.disconnected", label: "Repository disconnected" },
  { value: "repo.reindexed", label: "Re-index requested" },
  { value: "review.rerun", label: "Review re-run" },
  { value: "member.role_changed", label: "Member role changed" },
  // A group: the API matches every auth.* event.
  { value: "auth", label: "Auth (sign-in, sign-out, failed sign-in)" },
];

type Filters = { action: string; actor: string; q: string; since: string; until: string };
const EMPTY: Filters = { action: "", actor: "", q: "", since: "", until: "" };

// Each action's pill: a status tone, an icon and its label, so the colour is never
// the only cue. Additions read green, removals rose, re-runs blue, role changes amber.
const ACTION_STYLE: Record<string, { icon: LucideIcon; tone: string }> = {
  "repo.connected": { icon: PlugZap, tone: "border-status-ok-border bg-status-ok-bg text-status-ok" },
  "repo.disconnected": { icon: Unplug, tone: "border-status-blocking-border bg-status-blocking-bg text-status-blocking" },
  "repo.reindexed": { icon: RefreshCw, tone: "border-status-running-border bg-status-running-bg text-status-running" },
  "review.rerun": { icon: RotateCw, tone: "border-status-running-border bg-status-running-bg text-status-running" },
  "member.role_changed": { icon: UserCog, tone: "border-status-nit-border bg-status-nit-bg text-status-nit" },
  "auth.signed_in": { icon: LogIn, tone: "border-status-ok-border bg-status-ok-bg text-status-ok" },
  "auth.signed_out": { icon: LogOut, tone: "border-status-neutral-border bg-status-neutral-bg text-status-neutral" },
  "auth.sign_in_failed": { icon: ShieldAlert, tone: "border-status-blocking-border bg-status-blocking-bg text-status-blocking" },
};
const NEUTRAL_ACTION = {
  icon: ScrollText,
  tone: "border-status-neutral-border bg-status-neutral-bg text-status-neutral",
};

function ActionPill({ entry }: { entry: AuditEntry }) {
  const { icon: Icon, tone } = ACTION_STYLE[entry.action] ?? NEUTRAL_ACTION;
  return (
    <span className={cn("inline-flex h-6 items-center gap-1 rounded-full border px-2 text-micro whitespace-nowrap", tone)}>
      <Icon aria-hidden="true" className="size-3.5" />
      {entry.action_label}
    </span>
  );
}

/** What the current filters cover, in words - or that nothing narrows it. */
function Scope({ filters, total }: { filters: Filters; total: number | null }) {
  const action = AUDIT_ACTIONS.find((a) => a.value === filters.action && a.value);
  const parts = [
    action ? `action: ${action.label.toLowerCase()}` : "",
    filters.actor ? `actor: ${filters.actor}` : "",
    filters.q ? `target contains "${filters.q}"` : "",
    filters.since ? `from ${filters.since}` : "",
    filters.until ? `to ${filters.until}` : "",
  ].filter(Boolean);
  return (
    <div className="mb-4 flex flex-col gap-2 rounded-lg border bg-surface-2/50 px-3 py-2 text-xs text-fg-secondary sm:flex-row sm:items-center sm:justify-between">
      <p>
        {total !== null ? (
          <>
            <span className="font-mono text-fg tabular-nums">{total}</span> entr{total === 1 ? "y" : "ies"} ·{" "}
          </>
        ) : null}
        {parts.length ? parts.join(" · ") : "All activity in this organisation"}
      </p>
      <p className="flex items-center gap-1.5">
        <Lock aria-hidden="true" className="size-3.5 text-brand" />
        Append-only: entries cannot be edited or deleted
      </p>
    </div>
  );
}

function details(entry: AuditEntry) {
  const parts = Object.entries(entry.metadata ?? {}).map(([key, value]) => `${key.replace(/_/g, " ")}: ${String(value)}`);
  return parts.join(" · ");
}


function FilterForm({ initial, onApply }: { initial: Filters; onApply: (filters: Filters) => void }) {
  // A draft, applied together: typing in "actor" does not refetch per keystroke.
  const [draft, setDraft] = useState(initial);
  const set = (key: keyof Filters) => (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setDraft((current) => ({ ...current, [key]: event.target.value }));
  const active = Object.values(initial).some(Boolean);

  return (
    <form
      aria-label="Filter the audit log"
      className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-[repeat(5,minmax(0,1fr))_auto] lg:items-end"
      onSubmit={(event) => {
        event.preventDefault();
        onApply(draft);
      }}
    >
      <label className="flex flex-col gap-1 text-micro text-fg-secondary">
        Action
        <NativeSelect value={draft.action} onChange={set("action")}>
          {AUDIT_ACTIONS.map((action) => (
            <option key={action.value} value={action.value}>
              {action.label}
            </option>
          ))}
        </NativeSelect>
      </label>
      <label className="flex flex-col gap-1 text-micro text-fg-secondary">
        Actor
        <Input value={draft.actor} onChange={set("actor")} placeholder="GitHub login" />
      </label>
      <label className="flex flex-col gap-1 text-micro text-fg-secondary">
        Target contains
        <Input value={draft.q} onChange={set("q")} placeholder="e.g. codesage-testbed" />
      </label>
      <label className="flex flex-col gap-1 text-micro text-fg-secondary">
        From
        <Input type="date" value={draft.since} onChange={set("since")} />
      </label>
      <label className="flex flex-col gap-1 text-micro text-fg-secondary">
        To
        <Input type="date" value={draft.until} onChange={set("until")} />
      </label>
      <div className="flex gap-2">
        <Button type="submit" size="sm">
          Apply
        </Button>
        {active ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              setDraft(EMPTY);
              onApply(EMPTY);
            }}
          >
            Clear
          </Button>
        ) : null}
      </div>
    </form>
  );
}

function AuditLog() {
  const router = useRouter();
  const params = useSearchParams();
  const filters: Filters = {
    action: params.get("action") ?? "",
    actor: params.get("actor") ?? "",
    q: params.get("q") ?? "",
    since: params.get("since") ?? "",
    until: params.get("until") ?? "",
  };
  const page = Math.max(1, Number(params.get("page")) || 1);
  const request = { ...filters, page, page_size: PAGE_SIZE };
  const entries = useResource(() => api.auditLog(request), query(request));

  function go(next: Filters, nextPage = 1) {
    router.push(`/audit${query({ ...next, page: nextPage > 1 ? nextPage : undefined })}`);
  }

  const total = entries.data?.count ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const filtered = Object.values(filters).some(Boolean);

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Who connected, disconnected, re-indexed, re-ran or changed what, and when."
      />
      <Card>
        <CardContent>
          {entries.status === 403 ? (
            <EmptyState
              icon={Lock}
              title="Owners and admins only"
              description="The audit log is visible to organisation owners and admins."
            />
          ) : (
            <>
              <FilterForm key={query(filters)} initial={filters} onApply={(next) => go(next)} />
              <Scope filters={filters} total={entries.data ? total : null} />
              {entries.loading && !entries.data ? (
                <TableSkeleton rows={8} columns={4} label="Loading the audit log" />
              ) : entries.error ? (
                <ErrorState message={entries.error} onRetry={entries.reload} />
              ) : entries.data && entries.data.results.length > 0 ? (
                <>
                  <div className={entries.loading ? "opacity-50 transition-opacity" : undefined}>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>When</TableHead>
                          <TableHead>Actor</TableHead>
                          <TableHead>Action</TableHead>
                          <TableHead>Target</TableHead>
                          <TableHead className="hidden lg:table-cell">Details</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {entries.data.results.map((entry) => (
                          <TableRow key={entry.id}>
                            <TableCell className="whitespace-nowrap text-fg-secondary">
                              <time dateTime={entry.created_at} className="font-mono text-xs tabular-nums">
                                {formatDateTime(entry.created_at)}
                              </time>
                            </TableCell>
                            <TableCell>
                              <span className="inline-flex items-center gap-1.5 rounded-md border bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-fg">
                                <span
                                  aria-hidden="true"
                                  className="flex size-4 items-center justify-center rounded-sm bg-brand-tinted text-[0.625rem] font-semibold text-brand uppercase"
                                >
                                  {(entry.actor_login || "s").slice(0, 1)}
                                </span>
                                {entry.actor_login || "system"}
                              </span>
                            </TableCell>
                            <TableCell>
                              <ActionPill entry={entry} />
                            </TableCell>
                            <TableCell className="max-w-64" title={entry.target_label}>
                              <span className="inline-block max-w-full truncate rounded-md border bg-surface-1 px-1.5 py-0.5 align-middle font-mono text-xs text-fg">
                                {entry.target_label}
                              </span>
                            </TableCell>
                            <TableCell className="hidden max-w-80 truncate text-xs text-fg-secondary lg:table-cell" title={details(entry)}>
                              {details(entry)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                  <nav
                    aria-label="Pagination"
                    className="mt-3 flex items-center justify-between gap-2 border-t pt-3 text-sm text-fg-secondary"
                  >
                    <span>
                      Page <span className="font-mono text-fg tabular-nums">{page}</span> of{" "}
                      <span className="font-mono tabular-nums">{pages}</span>
                    </span>
                    <span className="flex gap-2">
                      <Button variant="outline" size="sm" disabled={!entries.data.previous} onClick={() => go(filters, page - 1)}>
                        <ChevronLeft aria-hidden="true" className="size-3.5" />
                        Previous
                      </Button>
                      <Button variant="outline" size="sm" disabled={!entries.data.next} onClick={() => go(filters, page + 1)}>
                        Next
                        <ChevronRight aria-hidden="true" className="size-3.5" />
                      </Button>
                    </span>
                  </nav>
                </>
              ) : (
                <EmptyState
                  icon={ScrollText}
                  title={filtered ? "No entries match these filters" : "Nothing recorded yet"}
                  description={
                    filtered
                      ? "Try a wider date range or clear a filter."
                      : "Connecting a repository, re-indexing, re-running a review or changing a role adds an entry here."
                  }
                />
              )}
            </>
          )}
        </CardContent>
      </Card>
    </>
  );
}

export default function AuditLogPage() {
  return (
    <Suspense fallback={<TableSkeleton rows={8} columns={4} label="Loading the audit log" />}>
      <AuditLog />
    </Suspense>
  );
}
