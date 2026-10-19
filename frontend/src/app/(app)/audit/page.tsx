"use client";

import { Lock, ScrollText } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/page-header";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useResource } from "@/hooks/use-resource";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

export default function AuditLogPage() {
  const [page, setPage] = useState(1);
  const entries = useResource(() => api.auditLog({ page }), `audit-${page}`);

  return (
    <>
      <PageHeader
        title="Audit log"
        description="Who connected, disconnected, re-indexed, re-ran or changed what. Entries cannot be edited or deleted."
      />
      <Card>
        <CardContent>
          {entries.loading ? (
            <TableSkeleton rows={8} columns={4} label="Loading the audit log" />
          ) : entries.status === 403 ? (
            <EmptyState
              icon={Lock}
              title="Owners and admins only"
              description="The audit log is visible to organisation owners and admins."
            />
          ) : entries.error ? (
            <ErrorState message={entries.error} onRetry={entries.reload} />
          ) : entries.data && entries.data.results.length > 0 ? (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>When</TableHead>
                    <TableHead>Actor</TableHead>
                    <TableHead>Action</TableHead>
                    <TableHead>Target</TableHead>
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
                      <TableCell className="max-w-72 truncate">{entry.target_label}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <nav aria-label="Pagination" className="mt-4 flex justify-end gap-2">
                <Button variant="outline" size="sm" disabled={!entries.data.previous} onClick={() => setPage(page - 1)}>
                  Previous
                </Button>
                <Button variant="outline" size="sm" disabled={!entries.data.next} onClick={() => setPage(page + 1)}>
                  Next
                </Button>
              </nav>
            </>
          ) : (
            <EmptyState
              icon={ScrollText}
              title="Nothing recorded yet"
              description="Connecting a repository, re-indexing, re-running a review or changing a role adds an entry here."
            />
          )}
        </CardContent>
      </Card>
    </>
  );
}
