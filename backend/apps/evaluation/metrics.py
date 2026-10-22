"""Scores over cached results. Counts, never bare percentages: every rate is reported
as k/n with a 95% Wilson interval, because on a few dozen cases the interval is the
point.

Runs of one case are not independent, so pooling them would overstate certainty.
Headline numbers therefore count each bug (or clean case) ONCE, by majority over its
valid runs - caught in more than half of them. Per-run pooled figures and the
run-to-run variance are reported beside them.

Amendments after DEV run 1, before any TEST run (eval/tools/README.md):
  H1  a finding credits at most one bug in a run (`matching.assign`), for every
      recall figure, anchoring and the per-agent table;
  H2  per-agent contribution counts only raw findings that survived into the
      review (kept or merged), never ones anchoring, citation or policy dropped;
  H3  recall at blocking severity, beside recall at any severity.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field

from apps.evaluation.matching import HEADLINE, LENIENT, assign, caught, on_the_line

# H2: what became of a raw finding that still reached the reader.
SURVIVED = frozenset({"kept", "merged"})

Z95 = 1.959963984540054


@dataclass(frozen=True)
class Count:
    k: int
    n: int

    @property
    def interval(self):
        return wilson(self.k, self.n)

    def __str__(self):
        if not self.n:
            return "0/0 (n/a)"
        low, high = self.interval
        return f"{self.k}/{self.n} ({round(low * 100)}–{round(high * 100)}%)"


def wilson(k, n, z=Z95):
    """95% Wilson score interval for k successes in n trials, as fractions."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def percentile(values, q):
    """Nearest-rank percentile; None for no values."""
    ordered = sorted(values)
    if not ordered:
        return None
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return ordered[rank - 1]


def majority(flags):
    """True when more than half of the runs say so."""
    return sum(flags) * 2 > len(flags)


@dataclass
class ArmScore:
    arm: str
    recall: Count = None
    recall_lenient: Count = None
    recall_blocking: Count = None
    recall_pooled: Count = None
    blocking_precision: Count = None
    false_alarms: Count = None
    anchoring: Count = None
    unstable_cases: Count = None
    valid_runs: int = 0
    invalid_runs: int = 0
    retries: int = 0
    latency_p50_ms: int | None = None
    latency_p95_ms: int | None = None
    cost_inr_mean: float | None = None
    per_agent: dict = field(default_factory=dict)


def score(cases, results, categories, arm):
    """Score one arm. `results` maps case id -> list of run results (dicts)."""
    out = ArmScore(arm=arm)
    bug_hits, bug_hits_lenient, bug_hits_blocking, pooled = [], [], [], [0, 0]
    blocking_total = blocking_matched = 0
    clean_flags, anchored = [], [0, 0]
    unstable = [0, 0]
    latencies, costs = [], []
    agent_hits = defaultdict(set)

    for case in cases:
        runs = results.get(case["id"], [])
        valid = [r for r in runs if r.get("valid")]
        out.valid_runs += len(valid)
        out.invalid_runs += sum(1 for r in runs if not r.get("valid"))
        out.retries += sum(int(r.get("attempts", 1)) - 1 for r in runs)
        if not valid:
            continue
        latencies += [r["duration_ms"] for r in valid]
        costs += [float(r.get("estimated_cost_inr") or 0) for r in valid]

        bugs = case["bugs"]
        verdicts = set()
        per_run = []  # (headline, lenient, blocking) assignments, one per valid run
        for run in valid:
            final = run["final_findings"]
            blocking = [f for f in final if f.get("severity") == "blocking"]
            # Precision asks whether a finding is about a planted bug at all, so a
            # second finding on the same bug is not counted as a false one.
            blocking_total += len(blocking)
            blocking_matched += sum(
                1 for f in blocking if any(caught([f], bug, HEADLINE, categories) for bug in bugs)
            )
            hits = assign(final, bugs, HEADLINE, categories)
            per_run.append(
                (
                    hits,
                    assign(final, bugs, LENIENT, categories),
                    assign(blocking, bugs, HEADLINE, categories),
                )
            )
            verdicts.add((bool(blocking), frozenset(hits)))
            for bug in bugs:
                pooled[0] += bug["id"] in hits
                pooled[1] += 1
                if bug["id"] in hits:
                    anchored[0] += on_the_line(hits[bug["id"]], bug)
                    anchored[1] += 1

            surviving = defaultdict(list)
            for raw in run.get("raw_findings", []):
                if raw.get("outcome") in SURVIVED:
                    surviving[raw["agent"]].append(raw)
            for agent, findings in surviving.items():
                for bug_id in assign(findings, bugs, HEADLINE, categories):
                    agent_hits[agent].add((case["id"], bug_id))

        for bug in bugs:
            bug_hits.append(majority([bug["id"] in run[0] for run in per_run]))
            bug_hits_lenient.append(majority([bug["id"] in run[1] for run in per_run]))
            bug_hits_blocking.append(majority([bug["id"] in run[2] for run in per_run]))
        if case.get("clean"):
            clean_flags.append(
                majority(
                    [
                        any(f.get("severity") == "blocking" for f in r["final_findings"])
                        for r in valid
                    ]
                )
            )
        if len(valid) > 1:
            unstable[1] += 1
            unstable[0] += len(verdicts) > 1

    out.recall = Count(sum(bug_hits), len(bug_hits))
    out.recall_lenient = Count(sum(bug_hits_lenient), len(bug_hits_lenient))
    out.recall_blocking = Count(sum(bug_hits_blocking), len(bug_hits_blocking))
    out.recall_pooled = Count(*pooled)
    out.blocking_precision = Count(blocking_matched, blocking_total)
    out.false_alarms = Count(sum(clean_flags), len(clean_flags))
    out.anchoring = Count(*anchored)
    out.unstable_cases = Count(*unstable)
    out.latency_p50_ms = percentile(latencies, 50)
    out.latency_p95_ms = percentile(latencies, 95)
    out.cost_inr_mean = round(sum(costs) / len(costs), 4) if costs else None
    total_bugs = len(bug_hits)
    out.per_agent = {
        agent: {
            "bugs_caught_any_run": len(hits),
            "unique": len(hits - set().union(*(h for a, h in agent_hits.items() if a != agent))),
            "of": total_bugs,
        }
        for agent, hits in sorted(agent_hits.items())
    }
    return out
