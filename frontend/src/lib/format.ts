/** Shared display formatting, so a duration or a cost reads the same everywhere. */

export function formatDuration(ms: number | null | undefined) {
  if (ms === null || ms === undefined) return "-";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
}

/** Always labelled as an estimate by the caller: CodeSage runs on free tiers. */
export function formatInr(value: string | number | null | undefined, digits = 2) {
  if (value === null || value === undefined || value === "") return "-";
  return `₹${Number(value).toFixed(digits)}`;
}

const RELATIVE = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

export function formatRelative(iso: string, now: number = Date.now()) {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000);
  const abs = Math.abs(seconds);
  if (abs < 60) return RELATIVE.format(seconds, "second");
  if (abs < 3600) return RELATIVE.format(Math.round(seconds / 60), "minute");
  if (abs < 86_400) return RELATIVE.format(Math.round(seconds / 3600), "hour");
  return RELATIVE.format(Math.round(seconds / 86_400), "day");
}

export function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export const AGENT_LABELS: Record<string, string> = {
  diff_intent: "Diff/Intent",
  static_analysis: "Static analysis",
  security: "Security",
  grounding: "Codebase grounding",
  test_coverage: "Test coverage",
  review: "Reviewer (v1)",
};
