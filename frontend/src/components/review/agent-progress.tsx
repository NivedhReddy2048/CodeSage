import { AGENT_LABELS } from "@/lib/format";
import type { AgentState } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * The five agents the progress socket counts, in the order the graph runs them:
 * Diff/Intent first, then the four that fan out. Synthesis is the merge after them,
 * not an agent that can be pending, so it has no segment.
 */
export const PROGRESS_AGENTS = ["diff_intent", "static_analysis", "security", "grounding", "test_coverage"] as const;

const TONE: Record<AgentState, string> = {
  pending: "bg-[color:var(--chart-empty)]",
  running: "bg-status-running motion-safe:animate-pulse",
  ok: "bg-brand",
  failed: "bg-status-blocking",
  skipped: "bg-status-neutral",
};

const WORD: Record<AgentState, string> = {
  pending: "waiting",
  running: "running",
  ok: "done",
  failed: "failed",
  skipped: "skipped",
};

/**
 * One segment per agent, coloured by its state, with the agent's name and state in
 * words underneath (and for screen readers) - so the bar never relies on colour.
 */
export function AgentProgress({ agents }: { agents: Partial<Record<string, AgentState>> }) {
  return (
    <ol aria-label="Agent progress" className="grid grid-cols-5 gap-1.5">
      {PROGRESS_AGENTS.map((name) => {
        const state = agents[name] ?? "pending";
        const label = AGENT_LABELS[name] ?? name;
        return (
          <li key={name} data-state={state} className="min-w-0">
            <span aria-hidden="true" className={cn("block h-1.5 rounded-full", TONE[state])} />
            <span className="sr-only">
              {label}: {WORD[state]}
            </span>
            {/* Visible: name and state on wider screens, the first word on a phone. */}
            <span aria-hidden="true" className="mt-1.5 block truncate text-[0.6875rem] text-fg-secondary">
              <span className="hidden sm:inline">
                {label} · {WORD[state]}
              </span>
              <span className="sm:hidden">{label.split(/[ /]/)[0]}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}
