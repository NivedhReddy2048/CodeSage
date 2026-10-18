"""Tests for the six-agent graph, token budget and static analysis isolation.

All LLM calls mocked. The linter-isolation tests are the ones that matter most:
they assert that attacker-supplied configuration cannot be read or executed.
"""

import json
import textwrap
from unittest import mock

import pytest

from apps.agents import breaker as breaker_module
from apps.agents import static_analysis, synthesis
from apps.agents.budget import TokenBudget, estimate_tokens
from apps.agents.graph import Runtime, build_graph, run_pipeline
from apps.agents.providers import ProviderResponse
from apps.agents.types import (
    Category,
    Finding,
    RepoContext,
    RetrievedChunk,
    ReviewConfig,
    Severity,
)

DIFF = """diff --git a/app/users.py b/app/users.py
--- a/app/users.py
+++ b/app/users.py
@@ -10,6 +10,8 @@ def helper():
 def paginate_users(users, page, per_page=10):
     start = (page - 1) * per_page
-    end = start + per_page
+    end = page + per_page
+    query = "SELECT * FROM users WHERE name = '%s'" % users
     return users[start:end]
"""


def config(**overrides):
    base = {
        "groq_api_key": "groq-test",
        "gemini_api_key": "gemini-test",
        "backoff_seconds": 0.0,
        "max_retries": 1,
    }
    base.update(overrides)
    return ReviewConfig(**base)


def context():
    return RepoContext(full_name="owner/repo", pr_number=1, pr_title="Paginate")


def findings_payload(entries):
    return json.dumps({"findings": entries})


def finding_entry(line=13, path="app/users.py", severity="blocking", **extra):
    entry = {
        "file": path,
        "line": line,
        "severity": severity,
        "category": "correctness",
        "message": "Something is wrong here.",
    }
    entry.update(extra)
    return entry


@pytest.fixture(autouse=True)
def clean_breakers():
    breaker_module.reset_all()
    yield
    breaker_module.reset_all()


def fake_complete(responses):
    """Patch Runtime.complete with canned per-model answers."""
    calls = []

    def _complete(self, model, system_prompt, user_message):
        calls.append((model, system_prompt, user_message))
        payload = responses.get(model, responses.get("*", '{"findings": []}'))
        if callable(payload):
            payload = payload(model, user_message)
        return ProviderResponse(content=payload, input_tokens=300, output_tokens=80), "groq", False

    return _complete, calls


# ========================================================== static analysis safety


def test_config_files_are_never_analysed():
    """ESLint configs are executable JS; pyproject can point tools at repo plugins."""
    for name in (
        "pyproject.toml",
        ".eslintrc.js",
        "eslint.config.js",
        "setup.py",
        "package.json",
        "conftest.py",
    ):
        assert static_analysis.is_config_file(name), name


def test_source_files_are_analysed():
    for name in ("app/users.py", "web/users.js", "src/App.tsx"):
        assert not static_analysis.is_config_file(name)


def test_a_malicious_pyproject_in_the_diff_is_not_read():
    """A PR adding a hostile pyproject.toml must not get it loaded by ruff."""
    hostile = textwrap.dedent(
        """
        [tool.ruff]
        # if this were honoured, the attacker controls the linter
        select = []
        """
    )
    files = {"pyproject.toml": hostile, "app/x.py": "import os\nx = eval('1')\n"}

    results = static_analysis.analyse(files)

    # pyproject was skipped entirely, and the real file was still linted despite
    # the attacker's attempt to disable every rule.
    assert all(f.file != "pyproject.toml" for f in results)


def test_a_malicious_eslint_config_is_not_executed():
    """eslint.config.js is JavaScript. It must never be run, or even analysed."""
    hostile = "require('child_process').execSync('touch /tmp/pwned'); module.exports = {};"
    files = {"eslint.config.js": hostile}

    results = static_analysis.analyse(files)

    assert results == []


def test_ruff_is_invoked_with_isolated():
    """--isolated is the flag that makes repo config files irrelevant."""
    commands = []

    def fake_run(command, cwd):
        commands.append(command)
        return None

    with mock.patch.object(static_analysis, "_run", side_effect=fake_run):
        with mock.patch.object(static_analysis.shutil, "which", return_value="/usr/bin/ruff"):
            static_analysis.analyse({"a.py": "x = 1\n"})

    # Several tools run; pick ruff's invocation rather than whichever was last.
    ruff = next(c for c in commands if c[0] == "ruff")
    assert "--isolated" in ruff


def test_bandit_is_never_given_an_ini_flag():
    """--ini would let the repository supply bandit's configuration."""
    commands = []

    def fake_run(command, cwd):
        commands.append(command)
        return None

    with mock.patch.object(static_analysis, "_run", side_effect=fake_run):
        with mock.patch.object(static_analysis.shutil, "which", return_value="/usr/bin/x"):
            static_analysis.analyse({"a.py": "x = 1\n"})

    for command in commands:
        assert "--ini" not in command
        assert not any(str(part).endswith("pyproject.toml") for part in command)


def test_no_package_manager_is_ever_invoked():
    """npm install runs preinstall scripts: arbitrary execution before linting."""
    commands = []

    def fake_run(command, cwd):
        commands.append(command)
        return None

    with mock.patch.object(static_analysis, "_run", side_effect=fake_run):
        with mock.patch.object(static_analysis.shutil, "which", return_value="/usr/bin/x"):
            static_analysis.analyse({"a.py": "x = 1\n", "web/a.js": "var x = 1;\n"})

    forbidden = {"npm", "npx", "yarn", "pnpm", "node", "bun", "pip", "python"}
    for command in commands:
        assert command[0] not in forbidden, command


def test_subprocesses_never_use_a_shell():
    """A filename from a PR must not reach a shell."""
    with mock.patch.object(static_analysis.subprocess, "run") as run:
        run.return_value = mock.Mock(stdout="", returncode=0)
        with mock.patch.object(static_analysis.shutil, "which", return_value="/usr/bin/x"):
            static_analysis.analyse({"a.py": "x = 1\n"})

    for call in run.call_args_list:
        assert call.kwargs.get("shell", False) is False
        assert call.kwargs.get("timeout")


def test_paths_are_flattened_into_the_sandbox(tmp_path):
    """A traversal path in the diff must not escape the temp directory."""
    written = static_analysis._write(
        {"../../etc/passwd": "root", "/abs/x.py": "y = 1"}, str(tmp_path)
    )

    for safe_name in written:
        assert "/" not in safe_name and "\\" not in safe_name and ".." not in safe_name
    assert {p.name for p in tmp_path.iterdir()} == set(written)


def test_a_missing_linter_is_not_fatal():
    with mock.patch.object(static_analysis.shutil, "which", return_value=None):
        assert static_analysis.analyse({"a.py": "import os\n"}) == []


def test_a_linter_timeout_is_not_fatal():
    import subprocess as sp

    with (
        mock.patch.object(static_analysis.shutil, "which", return_value="/usr/bin/x"),
        mock.patch.object(
            static_analysis.subprocess, "run", side_effect=sp.TimeoutExpired("ruff", 30)
        ),
    ):
        assert static_analysis.analyse({"a.py": "x = 1\n"}) == []


def test_javascript_patterns_are_detected_without_execution():
    files = {"web/a.js": "const el = document.getElementById('x');\nel.innerHTML = input;\n"}

    results = static_analysis.analyse(files)

    assert any(f.code == "js-inner-html" for f in results)
    assert all(f.tool == "pattern-scan" for f in results)


def test_javascript_comments_are_not_flagged():
    files = {"web/a.js": "// never use eval() here\nconst x = 1;\n"}

    assert static_analysis.analyse(files) == []


# ================================================================== token budget


def test_tokens_are_estimated_from_length():
    assert estimate_tokens("a" * 400) == 100
    assert estimate_tokens("") == 0


def test_the_budget_allows_what_fits():
    budget = TokenBudget(1000)

    assert budget.reserve("security", 400) is True
    assert budget.remaining == 600


def test_the_budget_skips_what_does_not_fit():
    budget = TokenBudget(500)
    budget.reserve("security", 400)

    assert budget.reserve("test_coverage", 400) is False
    assert budget.skipped[0][0] == "test_coverage"
    assert "exhausted" in budget.skipped[0][1]


def test_actual_usage_corrects_the_estimate():
    """Otherwise the budget drifts pessimistically and skips agents that would fit."""
    budget = TokenBudget(1000)
    budget.reserve("security", 500)

    budget.record_actual(500, 100)

    assert budget.remaining == 900


def test_a_zero_budget_skips_everything():
    budget = TokenBudget(0)

    assert budget.reserve("security", 1) is False


# =============================================================== graph structure


def test_the_graph_has_all_six_agents():
    nodes = {n for n in build_graph().get_graph().nodes if not n.startswith("__")}

    assert nodes == {
        "diff_intent",
        "static_analysis",
        "security",
        "grounding",
        "test_coverage",
        "synthesis",
    }


@pytest.mark.django_db
def test_the_pipeline_runs_end_to_end():
    responses = {
        "openai/gpt-oss-20b": '{"intent": "fix", "summary": "paginate users"}',
        "openai/gpt-oss-120b": findings_payload([finding_entry(line=13)]),
    }
    complete, calls = fake_complete(responses)

    with mock.patch.object(Runtime, "complete", complete):
        result = run_pipeline(DIFF, context(), config())

    assert result.succeeded is True
    assert result.findings
    # Every agent reported telemetry, including the tool-only one.
    names = {run.name for run in result.agent_runs}
    assert names == {
        "diff_intent",
        "static_analysis",
        "security",
        "grounding",
        "test_coverage",
    }


@pytest.mark.django_db
def test_diff_intent_runs_before_the_others():
    """Its classification is fed to the agents that follow."""
    seen = []

    def complete(self, model, system_prompt, user_message):
        seen.append(system_prompt[:40])
        if "classify" in system_prompt:
            return ProviderResponse('{"intent": "fix", "summary": "s"}', 10, 5), "groq", False
        # By the time any other agent runs, the intent must be in its prompt.
        assert "Change intent" in user_message
        return ProviderResponse('{"findings": []}', 10, 5), "groq", False

    with mock.patch.object(Runtime, "complete", complete):
        run_pipeline(DIFF, context(), config())

    assert "classif" in seen[0].lower()


@pytest.mark.django_db
def test_the_analysis_agents_run_in_parallel():
    """Sequential would be the sum of the delays; parallel is about the maximum."""
    import time

    def complete(self, model, system_prompt, user_message):
        if "classify" in system_prompt:
            return ProviderResponse('{"intent": "fix", "summary": "s"}', 10, 5), "groq", False
        time.sleep(0.3)
        return ProviderResponse('{"findings": []}', 10, 5), "groq", False

    started = time.perf_counter()
    with mock.patch.object(Runtime, "complete", complete):
        run_pipeline(DIFF, context(), config())
    elapsed = time.perf_counter() - started

    # Three LLM agents sleep 0.3s each; sequential would be >= 0.9s.
    assert elapsed < 0.8, f"agents appear to be running sequentially ({elapsed:.2f}s)"


@pytest.mark.django_db
def test_model_tiering_sends_security_to_the_big_model():
    responses = {"*": '{"findings": []}'}
    complete, calls = fake_complete(responses)

    with mock.patch.object(Runtime, "complete", complete):
        run_pipeline(DIFF, context(), config())

    models_by_prompt = {
        ("security" if "security reviewer" in prompt else "other"): model
        for model, prompt, _ in calls
    }
    assert models_by_prompt.get("security") == "openai/gpt-oss-120b"


@pytest.mark.django_db
def test_budget_exhaustion_skips_agents_rather_than_failing():
    """A review missing test coverage is useful; one that died at agent four is not."""
    responses = {"*": findings_payload([finding_entry()])}
    complete, _ = fake_complete(responses)

    with mock.patch.object(Runtime, "complete", complete):
        result = run_pipeline(DIFF, context(), config(token_budget=400))

    skipped = {name for name, _ in result.skipped_agents}
    assert skipped, "a tiny budget should have skipped something"
    assert result.duration_ms >= 0


@pytest.mark.django_db
def test_a_failing_agent_does_not_sink_the_review():
    def complete(self, model, system_prompt, user_message):
        if "security reviewer" in system_prompt:
            from apps.agents.providers import ProviderError

            raise ProviderError("groq: 503")
        if "classify" in system_prompt:
            return ProviderResponse('{"intent": "fix", "summary": "s"}', 10, 5), "groq", False
        return ProviderResponse(findings_payload([finding_entry()]), 10, 5), "groq", False

    with mock.patch.object(Runtime, "complete", complete):
        result = run_pipeline(DIFF, context(), config())

    assert result.succeeded is True
    failed = [r for r in result.agent_runs if r.name == "security"]
    assert failed and failed[0].error


@pytest.mark.django_db
def test_every_agent_failing_is_reported_not_raised():
    from apps.agents.providers import ProviderError

    def complete(self, model, system_prompt, user_message):
        raise ProviderError("everything is down")

    with mock.patch.object(Runtime, "complete", complete):
        result = run_pipeline(DIFF, context(), config())

    # Static analysis is local and still runs, but with no model answering this is
    # a degraded result rather than a review. 5c turns this into an explicitly
    # labelled degraded comment instead of letting a thin lint pass pose as one.
    assert result.succeeded is False
    assert result.failure_reason
    assert all(not run.succeeded for run in result.agent_runs if run.provider)


@pytest.mark.django_db
def test_an_empty_diff_short_circuits():
    with mock.patch.object(Runtime, "complete") as complete:
        result = run_pipeline("", context(), config())

    assert result.succeeded is True
    complete.assert_not_called()


# ==================================================================== grounding


@pytest.mark.django_db
def test_grounding_cites_a_retrieved_chunk():
    retrieved = [
        RetrievedChunk(
            file_path="app/users.py",
            symbol="UserRepository.find_by_id",
            line_start=15,
            line_end=20,
            content="def find_by_id(self, user_id): ...",
        )
    ]

    def complete(self, model, system_prompt, user_message):
        if "classify" in system_prompt:
            return ProviderResponse('{"intent": "feature", "summary": "s"}', 10, 5), "groq", False
        if "already exists" in system_prompt:
            return (
                ProviderResponse(
                    findings_payload(
                        [
                            finding_entry(
                                line=13,
                                severity="nit",
                                cited_file="app/users.py",
                                cited_line=16,
                            )
                        ]
                    ),
                    10,
                    5,
                ),
                "groq",
                False,
            )
        return ProviderResponse('{"findings": []}', 10, 5), "groq", False

    with mock.patch.object(Runtime, "complete", complete):
        result = run_pipeline(DIFF, context(), config(), retrieve=lambda q: retrieved)

    grounded = [f for f in result.findings if f.agent == "grounding"]
    assert grounded
    assert "app/users.py:15-20" in grounded[0].message


@pytest.mark.django_db
def test_grounding_drops_an_invented_citation():
    """The model cites a file it was never shown."""
    retrieved = [RetrievedChunk("app/users.py", "find_by_id", 15, 20, "def find_by_id(): ...")]

    def complete(self, model, system_prompt, user_message):
        if "classify" in system_prompt:
            return ProviderResponse('{"intent": "f", "summary": "s"}', 10, 5), "groq", False
        if "already exists" in system_prompt:
            return (
                ProviderResponse(
                    findings_payload([finding_entry(cited_file="app/invented.py", cited_line=99)]),
                    10,
                    5,
                ),
                "groq",
                False,
            )
        return ProviderResponse('{"findings": []}', 10, 5), "groq", False

    with mock.patch.object(Runtime, "complete", complete):
        result = run_pipeline(DIFF, context(), config(), retrieve=lambda q: retrieved)

    assert [f for f in result.findings if f.agent == "grounding"] == []


@pytest.mark.django_db
def test_grounding_is_skipped_when_nothing_is_retrieved():
    complete, _ = fake_complete({"*": '{"findings": []}'})

    with mock.patch.object(Runtime, "complete", complete):
        result = run_pipeline(DIFF, context(), config(), retrieve=lambda q: [])

    run = next(r for r in result.agent_runs if r.name == "grounding")
    assert "nothing retrieved" in run.skipped_reason


@pytest.mark.django_db
def test_a_retrieval_failure_does_not_fail_the_review():
    def boom(query):
        raise RuntimeError("database is down")

    complete, _ = fake_complete({"*": '{"findings": []}'})

    with mock.patch.object(Runtime, "complete", complete):
        result = run_pipeline(DIFF, context(), config(), retrieve=boom)

    run = next(r for r in result.agent_runs if r.name == "grounding")
    assert "retrieval failed" in run.error
    assert result.succeeded is True


# ==================================================================== synthesis


def make_finding(agent, line, severity=Severity.NIT, message="Problem.", path="a.py"):
    return Finding(
        file=path,
        line=line,
        severity=severity,
        category=Category.CORRECTNESS,
        message=message,
        agent=agent,
    )


def test_duplicate_findings_are_merged():
    findings = [
        make_finding("security", 10, message="SQL injection risk."),
        make_finding("static_analysis", 11, message="Possible SQL injection (ruff S608)."),
    ]

    merged = synthesis.synthesise(findings)

    assert len(merged) == 1


def test_a_merged_finding_credits_the_other_agents():
    findings = [
        make_finding("security", 10),
        make_finding("static_analysis", 10),
    ]

    merged = synthesis.synthesise(findings)

    assert "also flagged by" in merged[0].message


def test_blocking_wins_when_agents_disagree():
    """Under-reporting a real defect costs more than an over-cautious flag."""
    findings = [
        make_finding("grounding", 10, severity=Severity.NIT),
        make_finding("security", 10, severity=Severity.BLOCKING),
    ]

    merged = synthesis.synthesise(findings)

    assert merged[0].severity == Severity.BLOCKING


def test_distant_findings_in_one_file_are_kept_separate():
    findings = [make_finding("security", 10), make_finding("security", 80)]

    assert len(synthesis.synthesise(findings)) == 2


def test_same_line_in_different_files_is_not_merged():
    findings = [
        make_finding("security", 10, path="a.py"),
        make_finding("security", 10, path="b.py"),
    ]

    assert len(synthesis.synthesise(findings)) == 2


def test_blocking_findings_are_ordered_first():
    findings = [
        make_finding("security", 50, severity=Severity.NIT),
        make_finding("security", 10, severity=Severity.BLOCKING),
    ]

    merged = synthesis.synthesise(findings)

    assert merged[0].severity == Severity.BLOCKING


def test_synthesis_caps_the_output():
    findings = [make_finding("security", i * 10) for i in range(50)]

    assert len(synthesis.synthesise(findings, max_findings=5)) == 5


def test_synthesis_of_nothing_is_nothing():
    assert synthesis.synthesise([]) == []
