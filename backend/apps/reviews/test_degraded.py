"""Degraded mode and per-agent telemetry.

The degraded comment is the one piece of output that must never be mistaken for a
review: it appears precisely when nothing checked the code.
"""

from unittest import mock

import pytest

from apps.accounts.services import get_or_create_user_from_github
from apps.agents.types import AgentRun, Finding, ReviewResult, Severity
from apps.repos.models import AppInstallation, Repository
from apps.reviews import comment as comment_renderer
from apps.reviews import services
from apps.reviews.models import AgentRunRecord, PullRequest, Review

INSTALLATION_ID = 1

DIFF = """diff --git a/app/users.py b/app/users.py
--- a/app/users.py
+++ b/app/users.py
@@ -10,4 +10,4 @@ def helper():
 def paginate(users, page, per_page=10):
-    end = start + per_page
+    end = page + per_page
     return users[:end]
"""


@pytest.fixture
def pull_request(db):
    user, _ = get_or_create_user_from_github(
        {"id": 1, "login": "owner", "name": "", "email": "", "avatar_url": ""}
    )
    installation = AppInstallation.objects.create(
        installation_id=INSTALLATION_ID, account_login="owner"
    )
    repository = Repository.objects.create(
        organization=user.memberships.get().organization,
        installation=installation,
        github_id=1,
        full_name="owner/repo",
        owner="owner",
        name="repo",
    )
    return PullRequest.objects.create(
        repository=repository,
        number=1,
        title="Paginate",
        head_sha="abc1234def",
        ack_comment_id=99,
    )


def run(pull_request, result):
    with (
        mock.patch("apps.reviews.services.fetch_diff", return_value=DIFF),
        mock.patch("apps.reviews.services.run_pipeline", return_value=result),
        mock.patch("apps.reviews.services.github_app") as gh,
    ):
        gh.update_issue_comment.return_value = {"id": 99}
        gh.create_issue_comment.return_value = {"id": 99}
        review = services.review_pull_request(pull_request, INSTALLATION_ID)
    body = gh.update_issue_comment.call_args.args[3]
    return review, body


def ok_run(name, model="openai/gpt-oss-20b", provider="groq", findings=1):
    return AgentRun(
        name=name,
        model=model,
        provider=provider,
        input_tokens=300,
        output_tokens=90,
        latency_ms=900,
        succeeded=True,
        findings_count=findings,
    )


# =================================================================== telemetry


@pytest.mark.django_db
def test_every_agent_run_is_stored(pull_request):
    result = ReviewResult(
        findings=[],
        succeeded=True,
        model_used="openai/gpt-oss-120b",
        duration_ms=4000,
        agent_runs=[
            ok_run("diff_intent"),
            AgentRun(
                name="static_analysis",
                model="ruff+bandit+pattern-scan",
                succeeded=True,
                latency_ms=120,
                findings_count=2,
            ),
            ok_run("security", model="openai/gpt-oss-120b"),
            AgentRun(name="grounding", skipped_reason="nothing retrieved"),
            AgentRun(name="test_coverage", error="groq: 503"),
        ],
    )

    review, _ = run(pull_request, result)

    rows = AgentRunRecord.objects.filter(review=review)
    assert rows.count() == 5
    by_name = {r.name: r for r in rows}
    assert by_name["static_analysis"].provider == ""  # local tool, no provider
    assert by_name["grounding"].skipped_reason == "nothing retrieved"
    assert by_name["test_coverage"].error == "groq: 503"
    assert by_name["security"].model == "openai/gpt-oss-120b"


@pytest.mark.django_db
def test_the_comment_lists_which_agents_ran(pull_request):
    result = ReviewResult(
        findings=[],
        succeeded=True,
        duration_ms=1000,
        agent_runs=[
            ok_run("security", findings=0),
            AgentRun(name="grounding", skipped_reason="budget"),
        ],
    )

    _, body = run(pull_request, result)

    assert "Security" in body
    assert "Codebase grounding" in body
    assert "skipped" in body


@pytest.mark.django_db
def test_skipped_agents_are_explained(pull_request):
    """A six-agent review that quietly ran four must say so."""
    result = ReviewResult(
        findings=[],
        succeeded=True,
        duration_ms=1000,
        agent_runs=[ok_run("security")],
        skipped_agents=[("test_coverage", "token budget exhausted")],
    )

    _, body = run(pull_request, result)

    assert "token budget" in body


# ================================================================ degraded mode


@pytest.mark.django_db
def test_no_model_answering_is_degraded_not_successful(pull_request):
    """Static analysis alone is a partial signal, not a review."""
    result = ReviewResult(
        findings=[],
        succeeded=False,
        failure_reason="groq: 429; gemini: 429",
        duration_ms=800,
        agent_runs=[
            AgentRun(name="static_analysis", model="ruff", succeeded=True),
            AgentRun(name="security", model="x", provider="groq", error="429"),
        ],
    )

    review, body = run(pull_request, result)

    assert review.degraded is True
    assert review.status == Review.Status.FAILED
    assert "Degraded mode" in body


@pytest.mark.django_db
def test_the_degraded_comment_cannot_be_read_as_approval(pull_request):
    result = ReviewResult(
        findings=[],
        succeeded=False,
        failure_reason="all providers unavailable",
        agent_runs=[AgentRun(name="static_analysis", model="ruff", succeeded=True)],
    )

    _, body = run(pull_request, result)

    assert "has not been reviewed" in body
    assert "do not read this comment as" in body.lower()
    # The phrases a real review uses must be absent.
    assert "No issues found" not in body
    assert "### Blocking" not in body
    assert "### Nits" not in body


@pytest.mark.django_db
def test_the_degraded_comment_names_the_commit_and_reason(pull_request):
    result = ReviewResult(
        findings=[],
        succeeded=False,
        failure_reason="groq: quota exhausted",
        agent_runs=[AgentRun(name="static_analysis", model="ruff", succeeded=True)],
    )

    _, body = run(pull_request, result)

    assert "abc1234" in body
    assert "quota exhausted" in body


@pytest.mark.django_db
def test_degraded_discloses_that_local_analysis_ran(pull_request):
    result = ReviewResult(
        findings=[],
        succeeded=False,
        failure_reason="down",
        agent_runs=[AgentRun(name="static_analysis", model="ruff", succeeded=True)],
    )

    _, body = run(pull_request, result)

    assert "not a substitute" in body


@pytest.mark.django_db
def test_a_total_failure_is_not_marked_degraded(pull_request):
    """Nothing ran at all: that is a failure, with the ordinary failure comment."""
    result = ReviewResult(
        findings=[],
        succeeded=False,
        failure_reason="everything failed",
        agent_runs=[AgentRun(name="security", provider="groq", error="503")],
    )

    review, body = run(pull_request, result)

    assert review.degraded is False
    assert "Degraded mode" not in body
    assert "could not be completed" in body


@pytest.mark.django_db
def test_a_successful_review_is_not_degraded(pull_request):
    result = ReviewResult(
        findings=[Finding("app/users.py", 12, Severity.BLOCKING, "correctness", "Off by one.")],
        succeeded=True,
        duration_ms=2000,
        model_used="openai/gpt-oss-120b",
        agent_runs=[ok_run("security", model="openai/gpt-oss-120b")],
    )

    review, body = run(pull_request, result)

    assert review.degraded is False
    assert "Degraded mode" not in body
    assert "Off by one." in body


def test_the_degraded_body_differs_from_a_clean_review():
    """They must never be confusable, so the renderer is checked directly too."""
    review = mock.Mock(
        head_sha="abc1234",
        duration_ms=100,
        estimated_cost_inr=0,
        model_used="",
        used_fallback=False,
        truncated=False,
        skipped_files=[],
    )

    degraded = comment_renderer.render_degraded(review, "providers down", [])
    clean = comment_renderer.render(review, [])

    assert degraded != clean
    assert "No issues found" in clean
    assert "No issues found" not in degraded


# ================================================================== retrieval


@pytest.mark.django_db
def test_the_retriever_converts_rows_into_plain_chunks(pull_request):
    """The agents package must receive dataclasses, never ORM objects."""
    from apps.agents.types import RetrievedChunk
    from apps.ingestion.models import CodeChunk

    chunk = CodeChunk.objects.create(
        repository=pull_request.repository,
        file_path="app/users.py",
        symbol="find_by_id",
        line_start=15,
        line_end=20,
        content="def find_by_id(): ...",
        content_hash="h",
        search_text="app/users.py find_by_id find by id",
    )

    retriever = services.build_retriever(pull_request.repository)
    with mock.patch("apps.ingestion.retrieval.search", return_value=[(chunk, 0.9)]):
        results = retriever("find user by id")

    assert len(results) == 1
    assert isinstance(results[0], RetrievedChunk)
    assert results[0].file_path == "app/users.py"
    assert results[0].line_start == 15
