"use client";

import { Lock, ScrollText } from "lucide-react";
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

const PAGE_SIZE = 25;

export const AUDIT_ACTIONS = [
  { value: "", label: "Any action" },
  { value: "repo.connected", label: "Repository connected" },
  { value: "repo.disconnected", label: "Repository disconnected" },
  { value: "repo.reindexed", label: "Re-index requested" },
  { value: "review.rerun", label: "Review re-run" },
  { value: "member.role_changed", label: "Member role changed" },
];

type Filters = { action: string; actor: string; q: string; since: string; until: string };
const EMPTY: Filters = { action: "", actor: "", q: "", since: "", until: "" };

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
        description="Who connected, disconnected, re-indexed, re-ran or changed what. Entries cannot be edited or deleted."
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
                            <TableCell className="whitespace-nowrap text-muted-foreground">
                              <time dateTime={entry.created_at}>{formatDateTime(entry.created_at)}</time>
                            </TableCell>
                            <TableCell>{entry.actor_login || "system"}</TableCell>
                            <TableCell>{entry.action_label}</TableCell>
                            <TableCell className="max-w-64 truncate" title={entry.target_label}>
                              {entry.target_label}
                            </TableCell>
                            <TableCell className="hidden max-w-80 truncate text-xs text-muted-foreground lg:table-cell" title={details(entry)}>
                              {details(entry)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                  <nav
                    aria-label="Pagination"
                    className="mt-4 flex items-center justify-between gap-2 text-sm text-muted-foreground"
                  >
                    <span>
                      Page {page} of {pages} &middot; {total} entr{total === 1 ? "y" : "ies"}
                    </span>
                    <span className="flex gap-2">
                      <Button variant="outline" size="sm" disabled={!entries.data.previous} onClick={() => go(filters, page - 1)}>
                        Previous
                      </Button>
                      <Button variant="outline" size="sm" disabled={!entries.data.next} onClick={() => go(filters, page + 1)}>
                        Next
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
