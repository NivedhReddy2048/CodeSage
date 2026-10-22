"""Running cases through an arm, with a cache, a quota budget and a validity rule.

QUOTA. Groq limits apply per organisation and the binding one is gpt-oss-20b's
~200K tokens/day; a multi-agent run spends ~4.4K of it, the live dev stack shares
the rest. So multi-agent runs are capped per UTC day (35 by default, leaving
~10 reviews of headroom), at least `pace` seconds apart (8K tokens/minute), and every
attempt - valid or not - is appended to a ledger the cap is counted from.

CACHE. A result is reused when its case hash and pipeline version both match, so an
interrupted run resumes without spending quota twice and only changed cases re-run.

VALIDITY. The Gemini LLM fallback is switched off for evaluation: a run where any
model-backed agent failed at the provider (429s that outlasted the waits, timeouts,
outages) or fell back is INVALID. It is retried with backoff, and if it never comes
good it is stored as invalid and excluded from every metric - counted, never scored.
A schema failure is the model's own answer, not infrastructure, and stays valid.
"""

import hashlib
import json
import subprocess
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings

from apps.agents import run_pipeline
from apps.agents.providers import DAILY_LIMIT_MESSAGE
from apps.agents.types import RepoContext
from apps.evaluation import cases as case_store

DAILY_CAPS = {"pipeline": 35, "baseline": 60}
PACE_SECONDS = 60
RETRY_DELAYS = (60, 120, 240)
FREEZE_TAG = "eval-freeze-*"
FROZEN_PATHS = ("backend/apps/agents", "eval/cases", "eval/categories.json")


class EvalError(RuntimeError):
    """The evaluation cannot proceed as asked."""


def repo_root():
    return Path(settings.BASE_DIR).parent


def pipeline_version():
    """Hash of everything that decides what the pipeline says: its code and models."""
    digest = hashlib.sha256()
    agents = Path(settings.BASE_DIR) / "apps" / "agents"
    for path in sorted(agents.rglob("*.py")):
        digest.update(str(path.relative_to(agents)).replace("\\", "/").encode())
        digest.update(path.read_bytes())
    for name in ("REVIEW_PRIMARY_MODEL", "REVIEW_CHEAP_MODEL", "REVIEW_TOKEN_BUDGET"):
        digest.update(f"{name}={getattr(settings, name)}".encode())
    return digest.hexdigest()[:16]


def _git(*args):
    try:
        return subprocess.run(
            ["git", *args], cwd=repo_root(), capture_output=True, text=True, check=False
        )
    except OSError as exc:  # pragma: no cover - git is always present where this runs
        raise EvalError(f"git unavailable: {exc}") from exc


def harness_commit():
    return _git("rev-parse", "HEAD").stdout.strip()


def freeze_problem():
    """Why the TEST suite may not run now, or "" if it may.

    TEST runs once, after the prompts are frozen: only at a commit tagged
    eval-freeze-*, with no local change to the pipeline, the cases or the map.
    """
    tag = _git("describe", "--exact-match", "--tags", "--match", FREEZE_TAG, "HEAD")
    if tag.returncode != 0:
        return "TEST runs only at a commit tagged eval-freeze-* (prompts frozen)"
    dirty = _git("status", "--porcelain", "--", *FROZEN_PATHS).stdout.strip()
    if dirty:
        return f"TEST needs a clean tree at the freeze tag; changed:\n{dirty}"
    return ""


def eval_config():
    """The production config with the Gemini LLM fallback switched off."""
    from apps.reviews.services import build_config

    return replace(build_config(), gemini_api_key="")


def retriever_for(case):
    """Retrieval over the indexed repository, refused if the index has moved."""
    spec = case.get("retrieval")
    if not spec:
        return None
    from apps.ingestion.services import last_indexed_job
    from apps.repos.models import Repository
    from apps.reviews.services import build_retriever

    repository = Repository.objects.filter(full_name=spec["repository"]).first()
    if repository is None:
        raise EvalError(f"{case['id']}: {spec['repository']} is not connected here")
    job = last_indexed_job(repository)
    indexed = job.commit_sha if job else ""
    wanted = spec["index_commit"]
    if not indexed or not (indexed.startswith(wanted) or wanted.startswith(indexed)):
        raise EvalError(
            f"{case['id']}: index of {spec['repository']} is at {indexed[:12] or 'nothing'}, "
            f"the case needs {wanted[:12]}; results would not be comparable"
        )
    return build_retriever(repository)


def context_for(case):
    ctx = case.get("context") or {}
    return RepoContext(
        full_name=ctx.get("full_name", "eval/case"),
        pr_number=ctx.get("pr_number", 0),
        pr_title=ctx.get("title", ""),
        base_branch=ctx.get("base_branch", "main"),
        head_sha=ctx.get("head_sha", ""),
    )


def run_pipeline_arm(case, config):
    return run_pipeline(
        case["diff"],
        context_for(case),
        config,
        retrieve=retriever_for(case),
        fetch_source=lambda path: case_store.snapshot(case, path),
    )


def run_baseline_arm(case, config):
    from apps.agents.baseline import run_baseline

    return run_baseline(case["diff"], context_for(case), config)


ARMS = {"pipeline": run_pipeline_arm, "baseline": run_baseline_arm}


def daily_limit_hit(result):
    """Did a provider refuse because its per-day quota is spent?"""
    return any(DAILY_LIMIT_MESSAGE in (run.error or "") for run in result.agent_runs) or (
        DAILY_LIMIT_MESSAGE in (result.failure_reason or "")
    )


def invalid_reasons(result):
    """Infrastructure failures that make a run unfit to score. Empty means valid."""
    reasons = []
    if not result.succeeded:
        reasons.append(f"review did not complete: {result.failure_reason[:200]}")
    for run in result.agent_runs:
        if not (run.requested_model or run.provider):
            continue  # static analysis, or a skipped agent: not a model call
        if run.used_fallback:
            reasons.append(f"{run.name}: fell back to {run.provider}/{run.model}")
        elif run.error and not run.error.startswith("schema:"):
            reasons.append(f"{run.name}: {run.error[:200]}")
    return reasons


def _finding(f):
    return {
        "agent": f.agent,
        "file": f.file,
        "line": f.line,
        "severity": str(f.severity),
        "category": str(f.category),
        "placement": str(f.placement),
        "rule": f.rule,
        "message": f.message,
    }


def serialise(result, case, arm, run_index, started_at, finished_at, config):
    from apps.reviews.pricing import estimate_usd, to_inr

    usd = estimate_usd(result.calls)
    reasons = invalid_reasons(result)
    return {
        "case": case["id"],
        "suite": case["suite"],
        "arm": arm,
        "run": run_index,
        "case_hash": case_store.case_hash(case),
        "pipeline_version": pipeline_version(),
        "harness_commit": harness_commit(),
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_ms": result.duration_ms,
        "valid": not reasons,
        "invalid_reasons": reasons,
        "models": {"primary": config.primary_model, "cheap": config.cheap_model},
        "agents": [
            {
                "name": r.name,
                "model": r.model,
                "requested_model": r.requested_model,
                "provider": r.provider,
                "provider_model": r.provider_model,
                "system_fingerprint": r.system_fingerprint,
                "rate_limits": r.rate_limits,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "latency_ms": r.latency_ms,
                "succeeded": r.succeeded,
                "used_fallback": r.used_fallback,
                "skipped_reason": r.skipped_reason,
                "error": r.error,
                "findings_count": r.findings_count,
                "detail": r.detail,
            }
            for r in result.agent_runs
        ],
        "raw_findings": [
            {
                **_finding(t.finding),
                "cited_line": t.finding.cited_line,
                "anchored_by": t.finding.anchored_by,
                "evidence": t.finding.evidence,
                "downgraded": t.finding.downgraded,
                "outcome": t.outcome,
                "reason": t.reason,
            }
            for t in getattr(result, "trace", [])
        ],
        "final_findings": [_finding(f) for f in result.findings],
        "estimated_cost_usd": str(usd),
        "estimated_cost_inr": str(to_inr(usd)),
        "skipped_files": list(result.skipped_files),
        "truncated": result.truncated,
    }


class Store:
    """Cached results and the attempt ledger, under eval/results/."""

    def __init__(self, root):
        self.root = Path(root) / "results"

    def path(self, suite, arm, case_id, run_index):
        return self.root / suite / arm / case_id / f"run-{run_index}.json"

    def read(self, suite, arm, case_id, run_index):
        path = self.path(suite, arm, case_id, run_index)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def write(self, record):
        path = self.path(record["suite"], record["arm"], record["case"], record["run"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    @property
    def ledger(self):
        return self.root / "ledger.jsonl"

    def log_attempt(self, entry):
        self.root.mkdir(parents=True, exist_ok=True)
        with self.ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")

    def attempts_on(self, day, arm):
        if not self.ledger.exists():
            return 0
        count = 0
        for line in self.ledger.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            count += entry["day"] == day and entry["arm"] == arm
        return count

    def results(self, suite, arm):
        """{case id: [run records]} for scoring."""
        base = self.root / suite / arm
        out = {}
        if base.exists():
            for case_dir in sorted(p for p in base.iterdir() if p.is_dir()):
                out[case_dir.name] = [
                    json.loads(p.read_text(encoding="utf-8"))
                    for p in sorted(case_dir.glob("run-*.json"))
                ]
        return out


def usable(record, case, version):
    return bool(
        record
        and record.get("valid")
        and record.get("case_hash") == case_store.case_hash(case)
        and record.get("pipeline_version") == version
    )


def run_suite(
    root,
    suite,
    arms=("pipeline",),
    runs=1,
    *,
    caps=None,
    pace=PACE_SECONDS,
    retry_delays=RETRY_DELAYS,
    sleep=time.sleep,
    clock=lambda: datetime.now(UTC),
    log=print,
    config=None,
):
    """Run every case through every arm `runs` times. Returns a summary dict."""
    if suite == "test":
        problem = freeze_problem()
        if problem:
            raise EvalError(problem)
    caps = {**DAILY_CAPS, **(caps or {})}
    config = config or eval_config()
    version = pipeline_version()
    store = Store(root)
    summary = {"ran": 0, "cached": 0, "invalid": 0, "retries": 0, "stopped": ""}
    spent_any = False

    for case in case_store.load_suite(root, suite):
        for run_index in range(1, runs + 1):
            for arm in arms:
                if usable(store.read(suite, arm, case["id"], run_index), case, version):
                    summary["cached"] += 1
                    continue
                record = None
                for attempt in range(1, len(retry_delays) + 2):
                    day = clock().date().isoformat()
                    if store.attempts_on(day, arm) >= caps[arm]:
                        summary["stopped"] = f"daily cap of {caps[arm]} {arm} runs reached ({day})"
                        log(summary["stopped"] + "; rerun tomorrow to resume from the cache")
                        return summary
                    if spent_any:
                        sleep(pace)
                    spent_any = True
                    started = clock()
                    result = ARMS[arm](case, config)
                    if daily_limit_hit(result):
                        # Not the run's fault and not worth retrying: the quota is
                        # spent until it resets. Nothing is stored, so tomorrow's
                        # run picks this case up from where it stopped.
                        store.log_attempt(
                            {
                                "day": day,
                                "suite": suite,
                                "arm": arm,
                                "case": case["id"],
                                "run": run_index,
                                "attempt": attempt,
                                "valid": False,
                                "reasons": ["provider daily limit reached; stopped for the day"],
                                "started_at": started.isoformat(),
                            }
                        )
                        summary["stopped"] = (
                            f"provider daily limit reached at {case['id']} run {run_index} ({arm})"
                        )
                        log(summary["stopped"] + "; rerun tomorrow to resume from the cache")
                        return summary
                    record = serialise(result, case, arm, run_index, started, clock(), config)
                    record["attempts"] = attempt
                    store.log_attempt(
                        {
                            "day": day,
                            "suite": suite,
                            "arm": arm,
                            "case": case["id"],
                            "run": run_index,
                            "attempt": attempt,
                            "valid": record["valid"],
                            "reasons": record["invalid_reasons"],
                            "started_at": record["started_at"],
                        }
                    )
                    summary["ran"] += 1
                    if record["valid"]:
                        break
                    summary["retries"] += attempt <= len(retry_delays)
                    log(
                        f"{case['id']} run {run_index} ({arm}) invalid: {record['invalid_reasons']}"
                    )
                    if attempt <= len(retry_delays):
                        sleep(retry_delays[attempt - 1])
                if not record["valid"]:
                    summary["invalid"] += 1
                store.write(record)
                log(
                    f"{case['id']} run {run_index} ({arm}): "
                    f"{'valid' if record['valid'] else 'INVALID'}, "
                    f"{len(record['final_findings'])} findings, {record['duration_ms']} ms"
                )
    return summary
