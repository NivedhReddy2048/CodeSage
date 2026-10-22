"""Phase 8a: matching, metrics, the cache, validity, the budget and the freeze.

No LLM is called here: arms are replaced by fakes returning built ReviewResults.
"""

import json
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.agents.types import (
    AgentRun,
    Category,
    Finding,
    Placement,
    ReviewResult,
    Severity,
    TraceEntry,
)
from apps.evaluation import cases as case_store
from apps.evaluation import metrics, runner
from apps.evaluation.matching import HEADLINE, LENIENT, load_categories, matches, on_the_line

CATEGORIES_FILE = Path(__file__).resolve().parents[3] / "eval" / "categories.json"
CATEGORIES = load_categories(CATEGORIES_FILE)

BUG = {"id": "sqli", "file": "app/a.py", "lines": [10, 11], "category": "security"}


def finding(line, category="security", file="app/a.py", placement="inline", severity="blocking"):
    return {
        "file": file,
        "line": line,
        "category": category,
        "placement": placement,
        "severity": severity,
        "agent": "security",
    }


# ------------------------------------------------------------------- matching


@pytest.mark.parametrize(
    ("line", "headline", "lenient"),
    [
        (10, True, True),
        (11, True, True),
        (8, True, True),
        (13, True, True),
        (7, False, True),
        (14, False, True),
        (15, False, False),
    ],
)
def test_the_line_tolerances(line, headline, lenient):
    assert matches(finding(line), BUG, HEADLINE, CATEGORIES) is headline
    assert matches(finding(line), BUG, LENIENT, CATEGORIES) is lenient


def test_the_headline_needs_a_matching_category_and_lenient_does_not():
    wrong = finding(10, category="correctness")

    assert not matches(wrong, BUG, HEADLINE, CATEGORIES)
    assert matches(wrong, BUG, LENIENT, CATEGORIES)


def test_the_equivalence_map_accepts_correctness_for_a_null_check():
    null_check = {**BUG, "category": "error-handling"}

    assert matches(finding(10, category="correctness"), null_check, HEADLINE, CATEGORIES)
    assert not matches(finding(10, category="style"), null_check, HEADLINE, CATEGORIES)


def test_a_general_finding_has_no_line_to_credit():
    general = finding(10, placement="general")

    assert not matches(general, BUG, HEADLINE, CATEGORIES)
    assert matches(general, BUG, LENIENT, CATEGORIES)
    assert matches(finding(10, placement="existing"), BUG, HEADLINE, CATEGORIES)


def test_another_file_never_matches():
    assert not matches(finding(10, file="app/b.py"), BUG, LENIENT, CATEGORIES)


def test_anchoring_accuracy_is_the_exact_range_inline():
    assert on_the_line(finding(11), BUG)
    assert not on_the_line(finding(12), BUG)
    assert not on_the_line(finding(10, placement="existing"), BUG)


def test_the_category_map_covers_every_finding_category():
    assert set(CATEGORIES) == {c.value for c in Category}


# ------------------------------------------------------------------- metrics


def test_wilson_interval_and_its_format():
    """14/25 is 37.1–73.3% by the Wilson score formula (z = 1.96)."""
    low, high = metrics.wilson(14, 25)
    assert (round(low, 4), round(high, 4)) == (0.3707, 0.7333)
    assert str(metrics.Count(14, 25)) == "14/25 (37–73%)"
    assert metrics.wilson(0, 0) == (0.0, 1.0)
    low, high = metrics.wilson(0, 10)
    assert low == 0.0 and round(high, 3) == 0.278


def run(final, raw=(), valid=True, ms=1000, cost="0.0900", attempts=1):
    return {
        "valid": valid,
        "final_findings": list(final),
        "raw_findings": list(raw),
        "duration_ms": ms,
        "estimated_cost_inr": cost,
        "attempts": attempts,
    }


def test_score_arithmetic_against_a_hand_computed_fixture():
    """Two buggy cases (3 bugs) and two clean ones, three runs each.

    bug a1: caught in runs 1,2      -> majority yes
    bug a2: caught in run 1 only    -> majority no
    bug b1: caught in all 3         -> majority yes   => recall 2/3
    clean c: blocking in runs 1,2   -> false alarm
    clean d: blocking in run 3 only -> not a false alarm => false alarms 1/2
    """
    a1 = {"id": "a1", "file": "a.py", "lines": [5, 5], "category": "security"}
    a2 = {"id": "a2", "file": "a.py", "lines": [40, 40], "category": "correctness"}
    b1 = {"id": "b1", "file": "b.py", "lines": [3, 3], "category": "resource-leak"}
    cases = [
        {"id": "A", "bugs": [a1, a2], "clean": False},
        {"id": "B", "bugs": [b1], "clean": False},
        {"id": "C", "bugs": [], "clean": True},
        {"id": "D", "bugs": [], "clean": True},
    ]
    hit_a1 = {**finding(5, file="a.py"), "agent": "security"}
    hit_a2 = {
        **finding(41, category="correctness", file="a.py", severity="nit"),
        "agent": "test_coverage",
    }
    hit_b1 = {**finding(3, category="error-handling", file="b.py"), "agent": "static_analysis"}
    stray = finding(99, file="c.py")
    results = {
        "A": [
            run([hit_a1, hit_a2], raw=[hit_a1]),
            run([hit_a1]),
            run([], ms=3000),
            run([], valid=False, attempts=4),  # excluded, counted
        ],
        "B": [run([hit_b1], raw=[hit_b1]), run([hit_b1]), run([hit_b1], ms=2000)],
        "C": [run([stray]), run([stray]), run([])],
        "D": [run([]), run([]), run([stray])],
    }

    score = metrics.score(cases, results, CATEGORIES, "pipeline")

    assert (score.recall.k, score.recall.n) == (2, 3)
    assert (score.recall_lenient.k, score.recall_lenient.n) == (2, 3)
    # Pooled over valid runs: a1 2/3 + a2 1/3 + b1 3/3 = 6/9.
    assert (score.recall_pooled.k, score.recall_pooled.n) == (6, 9)
    assert (score.false_alarms.k, score.false_alarms.n) == (1, 2)
    # Blocking findings: A 2 (both hit a1), B 3 (all hit b1), C 2 + D 1 strays.
    assert (score.blocking_precision.k, score.blocking_precision.n) == (5, 8)
    # Matches: a1 x2, a2 x1 (41 is off its line), b1 x3 -> on the exact line 5 of 6.
    assert (score.anchoring.k, score.anchoring.n) == (5, 6)
    # Verdicts change across runs in A (hits differ), C and D (blocking differs).
    assert (score.unstable_cases.k, score.unstable_cases.n) == (3, 4)
    assert (score.valid_runs, score.invalid_runs, score.retries) == (12, 1, 3)
    assert (score.latency_p50_ms, score.latency_p95_ms) == (1000, 3000)
    assert score.cost_inr_mean == 0.09
    assert score.per_agent == {
        "security": {"bugs_caught_any_run": 1, "unique": 1, "of": 3},
        "static_analysis": {"bugs_caught_any_run": 1, "unique": 1, "of": 3},
    }


# ------------------------------------------------------------- fixture cases


NEW_FILE_DIFF = (
    "diff --git a/app/q.py b/app/q.py\nnew file mode 100644\n--- /dev/null\n+++ b/app/q.py\n"
    "@@ -0,0 +1,3 @@\n+def q(cur, name):\n"
    "+    cur.execute(f\"SELECT * FROM t WHERE n = '{name}'\")\n+    return cur.fetchall()\n"
)


def make_case(root, cid="c1", suite="dev", bugs=None, clean=False, diff=NEW_FILE_DIFF, **extra):
    case_dir = Path(root) / "cases" / suite / cid
    case_dir.mkdir(parents=True)
    bugs = (
        [
            {
                "id": "sqli",
                "file": "app/q.py",
                "lines": [2, 2],
                "category": "security",
                "kind": "added",
            }
        ]
        if bugs is None and not clean
        else (bugs or [])
    )
    case = {
        "id": cid,
        "suite": suite,
        "language": "python",
        "clean": clean,
        "source": {"kind": "planted"},
        "context": {"full_name": "o/r", "pr_number": 1, "title": "t"},
        "retrieval": None,
        "bugs": bugs,
        **extra,
    }
    (case_dir / "case.json").write_text(json.dumps(case), encoding="utf-8")
    (case_dir / "diff.patch").write_text(diff, encoding="utf-8")
    return case_dir


@pytest.fixture
def root(tmp_path):
    (tmp_path / "categories.json").write_text(CATEGORIES_FILE.read_text(encoding="utf-8"))
    return tmp_path


def test_a_sound_case_validates(root):
    make_case(root)

    assert case_store.validate(case_store.load_suite(root, "dev")[0], CATEGORIES) == []


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            {"bugs": [{"id": "x", "file": "app/q.py", "lines": [9, 9], "category": "security"}]},
            "do not start and end on added lines",
        ),
        (
            {"bugs": [{"id": "x", "file": "app/q.py", "lines": [2, 2], "category": "sql"}]},
            "not in the map",
        ),
        (
            {"bugs": [{"id": "x", "file": "app/zzz.py", "lines": [2, 2], "category": "security"}]},
            "not in the diff",
        ),
        (
            {
                "clean": True,
                "bugs": [{"id": "x", "file": "app/q.py", "lines": [2, 2], "category": "security"}],
            },
            "clean (no bugs) or has bugs",
        ),
    ],
)
def test_validation_catches_unsound_ground_truth(root, change, message):
    make_case(root, **change)

    problems = case_store.validate(case_store.load_suite(root, "dev")[0], CATEGORIES)

    assert any(message in p for p in problems), problems


MODIFIED_DIFF = (
    "diff --git a/app/m.py b/app/m.py\n--- a/app/m.py\n+++ b/app/m.py\n"
    "@@ -1,2 +1,2 @@\n import os\n-x = 1\n+x = 2\n"
)


def test_a_modified_file_needs_a_matching_snapshot(root):
    case_dir = make_case(root, diff=MODIFIED_DIFF, clean=True)
    case = case_store.load_suite(root, "dev")[0]
    assert any("has no files/app/m.py snapshot" in p for p in case_store.validate(case, CATEGORIES))

    (case_dir / "files" / "app").mkdir(parents=True)
    (case_dir / "files" / "app" / "m.py").write_text("import os\nx = 3\n")
    case = case_store.load_suite(root, "dev")[0]
    assert any("does not match the diff" in p for p in case_store.validate(case, CATEGORIES))

    (case_dir / "files" / "app" / "m.py").write_text("import os\nx = 2\n")
    case = case_store.load_suite(root, "dev")[0]
    assert case_store.validate(case, CATEGORIES) == []
    assert case_store.snapshot(case, "app/m.py") == "import os\nx = 2\n"
    assert case_store.snapshot(case, "../../../etc/passwd") is None


# ------------------------------------------------------------------- runner


def result(fallback=False, error="", findings=(), fingerprint="fp_1"):
    agent = AgentRun(
        name="security",
        model="openai/gpt-oss-120b",
        requested_model="openai/gpt-oss-120b",
        provider="gemini" if fallback else "groq",
        provider_model="openai/gpt-oss-120b",
        system_fingerprint=fingerprint,
        rate_limits={"x-ratelimit-remaining-tokens": "7000"},
        succeeded=not error,
        used_fallback=fallback,
        error=error,
    )
    final = [
        Finding(
            file="app/q.py",
            line=2,
            severity=Severity.BLOCKING,
            category=Category.SECURITY,
            message="SQL built from input.",
            agent="security",
            placement=Placement.INLINE,
            anchored_by="evidence",
            cited_line=3,
        )
        for _ in findings
    ]
    return ReviewResult(
        findings=final,
        agent_runs=[agent, AgentRun(name="static_analysis", succeeded=True)],
        trace=[TraceEntry(f, "kept", final_index=0) for f in final],
        succeeded=not error or error.startswith("schema:"),
        failure_reason="" if not error else error,
        duration_ms=4200,
    )


class FakeArm:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, case, config):
        self.calls += 1
        return self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]


@pytest.fixture
def fake(monkeypatch):
    def install(*outcomes):
        arm = FakeArm(*outcomes)
        monkeypatch.setitem(runner.ARMS, "pipeline", arm)
        return arm

    monkeypatch.setattr(runner, "harness_commit", lambda: "abc123")
    return install


def go(root, **kwargs):
    sleeps = []
    kwargs.setdefault("config", runner.eval_config())
    summary = runner.run_suite(root, "dev", sleep=sleeps.append, log=lambda *_: None, **kwargs)
    return summary, sleeps


def test_the_cache_prevents_a_second_llm_call(root, fake):
    make_case(root)
    arm = fake(result(findings=[1]))

    first, _ = go(root)
    second, _ = go(root)

    assert arm.calls == 1
    assert (first["ran"], second["ran"], second["cached"]) == (1, 0, 1)


def test_a_changed_case_runs_again(root, fake):
    case_dir = make_case(root)
    arm = fake(result())
    go(root)

    (case_dir / "diff.patch").write_text(NEW_FILE_DIFF.replace("t WHERE", "u WHERE"))
    go(root)

    assert arm.calls == 2


def test_every_result_records_models_fingerprints_limits_and_dates(root, fake):
    make_case(root)
    fake(result(findings=[1]))
    go(root)

    record = runner.Store(root).read("dev", "pipeline", "c1", 1)
    security = record["agents"][0]
    assert record["models"] == {"primary": "openai/gpt-oss-120b", "cheap": "openai/gpt-oss-20b"}
    assert security["system_fingerprint"] == "fp_1"
    assert security["provider_model"] == "openai/gpt-oss-120b"
    assert security["rate_limits"] == {"x-ratelimit-remaining-tokens": "7000"}
    assert datetime.fromisoformat(record["started_at"]).tzinfo is not None
    assert record["final_findings"][0]["line"] == 2
    assert record["raw_findings"][0]["cited_line"] == 3
    assert record["harness_commit"] == "abc123"


def test_a_fallback_run_is_invalid_retried_with_backoff_then_kept_when_valid(root, fake):
    make_case(root)
    fake(result(fallback=True), result(findings=[1]))

    summary, sleeps = go(root)

    record = runner.Store(root).read("dev", "pipeline", "c1", 1)
    assert record["valid"] and record["attempts"] == 2
    assert sleeps == [runner.RETRY_DELAYS[0], runner.PACE_SECONDS]
    assert (summary["retries"], summary["invalid"]) == (1, 0)


def test_a_run_that_never_comes_good_is_stored_invalid_and_excluded(root, fake):
    make_case(root)
    fake(result(error="groq: failed after 3 attempts (HTTP 429)"))

    summary, _ = go(root, retry_delays=(1, 1))

    record = runner.Store(root).read("dev", "pipeline", "c1", 1)
    assert not record["valid"]
    assert "HTTP 429" in record["invalid_reasons"][0]
    assert summary["invalid"] == 1
    score = metrics.score(
        case_store.load_suite(root, "dev"),
        runner.Store(root).results("dev", "pipeline"),
        CATEGORIES,
        "pipeline",
    )
    assert (score.valid_runs, score.invalid_runs, score.recall.n) == (0, 1, 0)


def test_a_schema_failure_is_the_models_answer_and_stays_valid():
    assert runner.invalid_reasons(result(error="schema: no JSON")) == []
    assert runner.invalid_reasons(result(fallback=True))
    assert runner.invalid_reasons(result(error="groq: timed out after 90s"))


def test_the_daily_cap_stops_the_run_and_the_next_day_resumes(root, fake):
    for cid in ("c1", "c2", "c3"):
        make_case(root, cid=cid)
    arm = fake(result())
    day1 = lambda: datetime(2026, 10, 23, 9, tzinfo=UTC)  # noqa: E731
    day2 = lambda: datetime(2026, 10, 24, 9, tzinfo=UTC)  # noqa: E731

    first, _ = go(root, caps={"pipeline": 2}, clock=day1)
    second, _ = go(root, caps={"pipeline": 2}, clock=day2)

    assert first["stopped"].startswith("daily cap of 2 pipeline runs reached (2026-10-23)")
    assert (first["ran"], second["ran"], second["cached"], arm.calls) == (2, 1, 2, 3)


def test_runs_are_paced_but_the_first_is_not_delayed(root, fake):
    make_case(root, cid="c1")
    make_case(root, cid="c2")
    fake(result())

    _, sleeps = go(root, pace=60)

    assert sleeps == [60]


def test_eval_never_falls_back_to_gemini():
    assert runner.eval_config().gemini_api_key == ""


def test_the_test_suite_refuses_to_run_unfrozen(root, fake, monkeypatch):
    make_case(root, suite="test")
    monkeypatch.setattr(
        runner, "freeze_problem", lambda: "TEST runs only at a commit tagged eval-freeze-*"
    )

    with pytest.raises(runner.EvalError, match="eval-freeze"):
        runner.run_suite(root, "test", sleep=lambda _: None, log=lambda *_: None)


def test_freeze_needs_the_tag_and_a_clean_tree(monkeypatch):
    class Done:
        def __init__(self, code=0, out=""):
            self.returncode, self.stdout = code, out

    monkeypatch.setattr(runner, "_git", lambda *a: Done(128) if a[0] == "describe" else Done())
    assert "eval-freeze" in runner.freeze_problem()
    monkeypatch.setattr(
        runner,
        "_git",
        lambda *a: Done(0, " M eval/cases/test/x/case.json") if a[0] == "status" else Done(),
    )
    assert "clean tree" in runner.freeze_problem()
    monkeypatch.setattr(runner, "_git", lambda *a: Done())
    assert runner.freeze_problem() == ""


@pytest.mark.django_db
def test_retrieval_is_refused_when_the_index_has_moved(root):
    from apps.ingestion.models import IngestionJob
    from tests import factories

    _, org = factories.user("alice")
    repo = factories.repository(org, "alice/testbed")
    IngestionJob.objects.create(
        repository=repo, status=IngestionJob.Status.DONE, commit_sha="b" * 40
    )
    case = {"id": "g1", "retrieval": {"repository": "alice/testbed", "index_commit": "a" * 40}}

    with pytest.raises(runner.EvalError, match="index of alice/testbed is at bbbbbbbbbbbb"):
        runner.retriever_for(case)
    assert runner.retriever_for(
        {**case, "retrieval": {**case["retrieval"], "index_commit": "b" * 40}}
    )


# ------------------------------------------------------------------ command


def test_the_command_checks_dry_runs_and_reports(root, fake):
    make_case(root)
    out = StringIO()

    call_command("run_eval", "--check", "--root", str(root), stdout=out)
    assert "1 case(s) valid" in out.getvalue()

    out = StringIO()
    call_command(
        "run_eval", "--suite", "dev", "--runs", "3", "--dry-run", "--root", str(root), stdout=out
    )
    assert "3 runs to do" in out.getvalue()
    assert "~13K gpt-oss-20b" in out.getvalue()

    fake(result(findings=[1]))
    go(root)
    out = StringIO()
    call_command("run_eval", "--suite", "dev", "--report", "--root", str(root), stdout=out)
    assert "recall               1/1 (21–100%)" in out.getvalue()


def test_the_check_fails_loudly_on_a_bad_case(root):
    make_case(root, bugs=[{"id": "x", "file": "app/q.py", "lines": [9, 9], "category": "security"}])

    with pytest.raises(CommandError, match="1 problem"):
        call_command("run_eval", "--check", "--root", str(root), stdout=StringIO())


def test_a_bug_range_may_hold_an_unchanged_line_but_not_leave_the_hunk(root):
    """thefuck-3: the fix changed lines 108 and 110 with line 109 kept between them."""
    diff = (
        "diff --git a/app/m.py b/app/m.py\n--- a/app/m.py\n+++ b/app/m.py\n"
        "@@ -1,3 +1,3 @@\n-x = 1\n+x = 2\n y = 0\n-z = 1\n+z = 2\n"
    )
    case_dir = make_case(
        root,
        diff=diff,
        bugs=[{"id": "b", "file": "app/m.py", "lines": [1, 3], "category": "correctness"}],
    )
    (case_dir / "files" / "app").mkdir(parents=True)
    (case_dir / "files" / "app" / "m.py").write_text("x = 2\ny = 0\nz = 2\n")
    assert case_store.validate(case_store.load_suite(root, "dev")[0], CATEGORIES) == []

    data = json.loads((case_dir / "case.json").read_text())
    data["bugs"][0]["lines"] = [1, 5]
    (case_dir / "case.json").write_text(json.dumps(data))
    problems = case_store.validate(case_store.load_suite(root, "dev")[0], CATEGORIES)
    assert any("do not start and end" in p for p in problems), problems


def test_every_committed_fixture_is_sound():
    """CI guard: no case under eval/cases/ may land with unsound ground truth."""
    root = CATEGORIES_FILE.parent
    problems = [
        problem
        for suite in sorted(case_store.SUITES)
        for case in case_store.load_suite(root, suite)
        for problem in case_store.validate(case, CATEGORIES)
    ]
    assert problems == []


def test_a_daily_limit_stops_the_day_cleanly_and_tomorrow_resumes(root, fake):
    """No invalid record, no retry: the quota is spent, not the run broken."""
    for cid in ("c1", "c2", "c3"):
        make_case(root, cid=cid)
    daily = result(error="groq: daily limit reached (HTTP 429: ... tokens per day (TPD))")
    arm = fake(result(findings=[1]), daily)
    day1 = lambda: datetime(2026, 10, 23, 9, tzinfo=UTC)  # noqa: E731
    day2 = lambda: datetime(2026, 10, 24, 9, tzinfo=UTC)  # noqa: E731

    first, sleeps = go(root, clock=day1)

    store = runner.Store(root)
    assert first["stopped"] == "provider daily limit reached at c2 run 1 (pipeline)"
    assert (first["ran"], first["invalid"], first["retries"]) == (1, 0, 0)
    assert store.read("dev", "pipeline", "c2", 1) is None  # nothing stored for c2
    assert sleeps == [runner.PACE_SECONDS]  # pacing only, no retry backoff

    arm.outcomes = [result(findings=[1])]
    second, _ = go(root, clock=day2)

    assert (second["cached"], second["ran"], second["stopped"]) == (1, 2, "")
    assert all(store.read("dev", "pipeline", c, 1)["valid"] for c in ("c1", "c2", "c3"))
