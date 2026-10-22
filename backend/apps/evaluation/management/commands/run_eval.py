"""Phase 8 evaluation (docs/EVALUATION.md).

    python manage.py run_eval --check                      validate fixtures, no LLM call
    python manage.py run_eval --suite dev --dry-run        what would run, and its quota
    python manage.py run_eval --suite dev --runs 1         run (resumes from the cache)
    python manage.py run_eval --suite dev --report         score the cached results

TEST runs only at a commit tagged eval-freeze-* with a clean tree.
"""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.evaluation import cases as case_store
from apps.evaluation import metrics, runner
from apps.evaluation.matching import load_categories

# Measured on the live pipeline (Oct 21-22): 3 gpt-oss-20b calls of ~1.48K tokens and
# one gpt-oss-120b call of ~1.03K per multi-agent review.
TOKENS_PER_RUN = {"pipeline": {"gpt-oss-20b": 4400, "gpt-oss-120b": 1030}}


class Command(BaseCommand):
    help = "Run or score the Phase 8 evaluation."

    def add_arguments(self, parser):
        parser.add_argument("--suite", choices=sorted(case_store.SUITES))
        parser.add_argument("--arm", action="append", choices=sorted(runner.ARMS))
        parser.add_argument("--runs", type=int, default=1)
        parser.add_argument("--check", action="store_true", help="validate fixtures only")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--report", action="store_true")
        parser.add_argument("--max-runs-per-day", type=int)
        parser.add_argument("--pace", type=int, default=runner.PACE_SECONDS)
        parser.add_argument("--root", default=str(settings.EVAL_ROOT))

    def handle(self, *args, **opts):
        root = opts["root"]
        categories = load_categories(f"{root}/categories.json")
        suites = [opts["suite"]] if opts["suite"] else sorted(case_store.SUITES)

        if opts["check"]:
            return self._check(root, suites, categories)
        if not opts["suite"]:
            raise CommandError("--suite is required (except with --check)")
        arms = tuple(opts["arm"] or ["pipeline"])
        suite_cases = case_store.load_suite(root, opts["suite"])
        if not suite_cases:
            raise CommandError(f"no cases in {root}/cases/{opts['suite']}")

        if opts["report"]:
            store = runner.Store(root)
            report = {
                arm: metrics.score(suite_cases, store.results(opts["suite"], arm), categories, arm)
                for arm in arms
            }
            for arm, score in report.items():
                self.stdout.write(f"\n== {opts['suite']} / {arm}")
                for name in (
                    "recall",
                    "recall_lenient",
                    "recall_pooled",
                    "blocking_precision",
                    "false_alarms",
                    "anchoring",
                    "unstable_cases",
                ):
                    self.stdout.write(f"  {name:20} {getattr(score, name)}")
                self.stdout.write(
                    f"  valid runs {score.valid_runs}, invalid {score.invalid_runs}, "
                    f"retries {score.retries}; latency p50 {score.latency_p50_ms} ms, "
                    f"p95 {score.latency_p95_ms} ms; cost/run INR {score.cost_inr_mean}"
                )
                self.stdout.write(f"  per agent: {json.dumps(score.per_agent)}")
            return None

        if opts["dry_run"]:
            store = runner.Store(root)
            version = runner.pipeline_version()
            todo = [
                (case["id"], run, arm)
                for case in suite_cases
                for run in range(1, opts["runs"] + 1)
                for arm in arms
                if not runner.usable(store.read(opts["suite"], arm, case["id"], run), case, version)
            ]
            self.stdout.write(f"{len(todo)} runs to do (pipeline version {version}):")
            for arm in arms:
                n = sum(1 for _, _, a in todo if a == arm)
                tokens = TOKENS_PER_RUN.get(arm, {})
                spend = ", ".join(f"~{n * t // 1000}K {m}" for m, t in tokens.items())
                cap = opts["max_runs_per_day"] or runner.DAILY_CAPS[arm]
                self.stdout.write(
                    f"  {arm}: {n} runs ({spend}), {-(-n // cap)} day(s) at {cap}/day"
                )
            return None

        caps = {arm: opts["max_runs_per_day"] for arm in arms} if opts["max_runs_per_day"] else {}
        try:
            summary = runner.run_suite(
                root,
                opts["suite"],
                arms,
                opts["runs"],
                caps=caps,
                pace=opts["pace"],
                log=self.stdout.write,
            )
        except runner.EvalError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(summary))
        return None

    def _check(self, root, suites, categories):
        problems, total = [], 0
        for suite in suites:
            for case in case_store.load_suite(root, suite):
                total += 1
                problems += case_store.validate(case, categories)
        for problem in problems:
            self.stdout.write(f"  x {problem}")
        if problems:
            raise CommandError(f"{len(problems)} problem(s) in {total} case(s)")
        self.stdout.write(f"{total} case(s) valid")
