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

const chip = "inline-block max-w-full truncate rounded-md border bg-surface-2 px-1.5 py-0.5 font-mono text-[0.6875rem] text-fg";

/**
 * A trace matrix: one row per agent with the model that actually served it (and
 * what it asked for, after a failover), provider, tokens and latency. Latency also
 * gets a bar scaled to the slowest agent in this review, so the critical path shows
 * at a glance; the number beside it is what to read.
 */
export function AgentsTable({ runs }: { runs: AgentRun[] }) {
  const slowest = Math.max(1, ...runs.map((run) => run.latency_ms || 0));

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Agent</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Model (served)</TableHead>
          <TableHead className="hidden md:table-cell">Provider</TableHead>
          <TableHead className="text-right">Tokens in / out</TableHead>
          <TableHead className="w-44 text-right">Latency</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => {
          const detail = note(run);
          return (
            <TableRow key={run.id}>
              <TableCell className="align-top">
                <span className="font-medium text-fg">{AGENT_LABELS[run.name] ?? run.name}</span>
                {detail ? (
                  <span className="block max-w-64 truncate text-xs text-fg-secondary" title={detail}>
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
              <TableCell className="max-w-56 align-top">
                {run.model ? <code className={chip}>{run.model}</code> : <span className="text-fg-secondary">-</span>}
                {run.used_fallback && run.requested_model ? (
                  <span className="mt-1 block text-xs text-fg-secondary">
                    asked for <code className="font-mono">{run.requested_model}</code>
                  </span>
                ) : null}
              </TableCell>
              <TableCell className="hidden align-top md:table-cell">
                {run.provider ? <code className={chip}>{run.provider}</code> : <span className="text-fg-secondary">-</span>}
              </TableCell>
              <TableCell className="text-right align-top font-mono tabular-nums">
                {run.input_tokens || run.output_tokens
                  ? `${run.input_tokens} / ${run.output_tokens}`
                  : "-"}
              </TableCell>
              <TableCell className="align-top">
                <span className="flex items-center justify-end gap-2">
                  {run.latency_ms ? (
                    <span aria-hidden="true" className="hidden h-1.5 w-20 overflow-hidden rounded-full bg-[color:var(--chart-empty)] sm:block">
                      <span
                        className="block h-full rounded-full bg-[color:var(--chart-secondary)]"
                        style={{ width: `${Math.max(4, (run.latency_ms / slowest) * 100)}%` }}
                      />
                    </span>
                  ) : null}
                  <span className="w-14 text-right font-mono tabular-nums">{run.latency_ms ? formatDuration(run.latency_ms) : "-"}</span>
                </span>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
