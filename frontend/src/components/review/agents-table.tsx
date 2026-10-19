import { StatusBadge, type StatusKind } from "@/components/status-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { AGENT_LABELS, formatDuration } from "@/lib/format";
import type { AgentRun } from "@/lib/types";

function kindOf(run: AgentRun): StatusKind {
  if (run.skipped_reason) return "skipped";
  return run.succeeded ? "ok" : "failed";
}

/** Why it did not run, or what went wrong, in the short public form. */
function note(run: AgentRun) {
  if (run.skipped_reason) return run.skipped_reason;
  if (!run.succeeded) return run.error_summary || "No usable output";
  return run.detail;
}

/**
 * One row per agent: the model that actually served it (and what it asked for, after
 * a failover), provider, tokens, latency and outcome.
 */
export function AgentsTable({ runs }: { runs: AgentRun[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Agent</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Model (served)</TableHead>
          <TableHead className="hidden md:table-cell">Provider</TableHead>
          <TableHead className="text-right">Tokens</TableHead>
          <TableHead className="text-right">Latency</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => {
          const detail = note(run);
          return (
            <TableRow key={run.id}>
              <TableCell className="align-top">
                <span className="font-medium">{AGENT_LABELS[run.name] ?? run.name}</span>
                {detail ? (
                  <span className="block max-w-64 truncate text-xs text-muted-foreground" title={detail}>
                    {detail}
                  </span>
                ) : null}
              </TableCell>
              <TableCell className="align-top">
                <div className="flex flex-wrap gap-1">
                  <StatusBadge kind={kindOf(run)} />
                  {run.used_fallback ? <StatusBadge kind="fallback" /> : null}
                </div>
              </TableCell>
              <TableCell className="align-top">
                {run.model ? <code className="text-xs">{run.model}</code> : <span className="text-muted-foreground">-</span>}
                {run.used_fallback && run.requested_model ? (
                  <span className="block text-xs text-muted-foreground">
                    asked for <code>{run.requested_model}</code>
                  </span>
                ) : null}
              </TableCell>
              <TableCell className="hidden align-top md:table-cell">{run.provider || "-"}</TableCell>
              <TableCell className="text-right align-top tabular-nums">
                {run.input_tokens || run.output_tokens
                  ? `${run.input_tokens} / ${run.output_tokens}`
                  : "-"}
              </TableCell>
              <TableCell className="text-right align-top tabular-nums">
                {run.latency_ms ? formatDuration(run.latency_ms) : "-"}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
