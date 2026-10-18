"""Tests for review persistence, cost estimation and the PR comment.

LLM and GitHub calls are mocked throughout: no network, no quota spent in CI.
"""

import json
from decimal import Decimal
from unittest import mock

import pytest

from apps.accounts.services import get_or_create_user_from_github
from apps.agents.types import Finding, ReviewResult, Severity
from apps.agents.types import LLMCall as AgentCall
from apps.repos.models import AppInstallation, Repository
from apps.reviews import comment as comment_renderer
from apps.reviews import services
from apps.reviews.models import LLMCall, PullRequest, Review, ReviewFinding
from apps.reviews.pricing import estimate_usd, format_footer, to_inr, unpriced_models

INSTALLATION_ID = 172631969

DIFF = """diff --git a/app/users.py b/app/users.py
--- a/app/users.py
+++ b/app/users.py
@@ -10,5 +10,5 @@ def helper():
 def paginate_users(users, page, per_page=10):
     start = (page - 1) * per_page
-    end = start + per_page
+    end = page + per_page
     return users[start:end]
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
        default_branch="main",
    )
    return PullRequest.objects.create(
        repository=repository,
        number=1,
        title="Fix pagination",
        head_sha="abc1234def5678",
        ack_comment_id=4242,
    )


def agent_result(**overrides):
    base = {
        "findings": [
            Finding(
                file="app/users.py",
                line=13,
                severity=Severity.BLOCKING,
                category="correctness",
                message="Off-by-one: end should be start + per_page.",
            )
        ],
        "calls": [
            AgentCall(
                provider="groq",
                model="openai/gpt-oss-120b",
                input_tokens=1000,
                output_tokens=500,
                latency_ms=1500,
                succeeded=True,
            )
        ],
        "duration_ms": 1600,
        "succeeded": True,
        "model_used": "openai/gpt-oss-120b",
    }
    base.update(overrides)
    return ReviewResult(**base)


def run(pull_request, result, diff=DIFF):
    with (
        mock.patch("apps.reviews.services.fetch_diff", return_value=diff),
        mock.patch("apps.reviews.services.run_pipeline", return_value=result),
        mock.patch("apps.reviews.services.github_app") as gh,
    ):
        gh.update_issue_comment.return_value = {"id": 4242}
        gh.create_issue_comment.return_value = {"id": 4242}
        review = services.review_pull_request(pull_request, INSTALLATION_ID)
    return review, gh


# ======================================================================== pricing


def test_cost_is_computed_from_the_price_table():
    """gpt-oss-120b is $0.15 in / $0.60 out per 1M (Groq docs, 2026-10-18)."""
    calls = [
        AgentCall(
            provider="groq",
            model="openai/gpt-oss-120b",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
    ]

    assert estimate_usd(calls) == Decimal("0.750000")


def test_cost_scales_with_tokens():
    calls = [
        AgentCall(
            provider="groq",
            model="openai/gpt-oss-120b",
            input_tokens=10_000,
            output_tokens=2_000,
        )
    ]

    # 10k * 0.15/1M + 2k * 0.60/1M = 0.0015 + 0.0012
    assert estimate_usd(calls) == Decimal("0.002700")


def test_failed_calls_still_count_toward_cost():
    """A retry that produced nothing still consumed input tokens."""
    calls = [
        AgentCall(
            provider="groq",
            model="openai/gpt-oss-120b",
            input_tokens=1000,
            output_tokens=10,
            succeeded=False,
        ),
        AgentCall(
            provider="groq",
            model="openai/gpt-oss-120b",
            input_tokens=1000,
            output_tokens=50,
            succeeded=True,
        ),
    ]

    assert estimate_usd(calls) > Decimal("0")


def test_an_unknown_model_contributes_nothing_and_is_reported():
    """A made-up price looks exactly as authoritative as a real one."""
    calls = [AgentCall(provider="x", model="mystery-model", input_tokens=1_000_000)]

    assert estimate_usd(calls) == Decimal("0.000000")
    assert unpriced_models(calls) == ["mystery-model"]


def test_inr_conversion_uses_the_fixed_rate(settings):
    settings.USD_TO_INR = 95.06

    assert to_inr(Decimal("1.0")) == Decimal("95.0600")


def test_the_footer_labels_the_cost_an_estimate():
    footer = format_footer(12000, Decimal("0.40"), "openai/gpt-oss-120b", False)

    assert "Reviewed in 12 s" in footer
    assert "est." in footer
    assert "at paid-tier rates" in footer
    assert "openai/gpt-oss-120b" in footer


def test_the_footer_marks_a_fallback():
    footer = format_footer(9000, Decimal("0.10"), "gemini-flash-lite-latest", True)

    assert "(fallback)" in footer


def test_the_footer_says_unknown_rather_than_printing_a_false_zero():
    footer = format_footer(1000, Decimal("0"), "mystery", False, unpriced=["mystery"])

    assert "cost unknown" in footer
    assert "est." not in footer


def test_sub_second_reviews_are_reported_in_milliseconds():
    assert "ms" in format_footer(420, Decimal("0.01"), "m", False)


# ===================================================================== persistence


@pytest.mark.django_db
def test_a_successful_review_stores_findings_and_telemetry(pull_request):
    review, _ = run(pull_request, agent_result())

    assert review.status == Review.Status.DONE
    assert review.head_sha == "abc1234def5678"
    assert review.model_used == "openai/gpt-oss-120b"
    assert review.used_fallback is False
    assert review.total_input_tokens == 1000
    assert review.total_output_tokens == 500
    assert review.estimated_cost_usd > 0
    assert review.estimated_cost_inr > 0

    finding = ReviewFinding.objects.get(review=review)
    assert finding.file_path == "app/users.py"
    assert finding.line == 13
    assert finding.severity == "blocking"
    assert finding.category == "correctness"

    call = LLMCall.objects.get(review=review)
    assert call.provider == "groq"
    assert call.latency_ms == 1500
    assert call.succeeded is True


@pytest.mark.django_db
def test_every_call_is_stored_including_failures(pull_request):
    result = agent_result(
        calls=[
            AgentCall(provider="groq", model="openai/gpt-oss-120b", error="HTTP 429"),
            AgentCall(
                provider="gemini",
                model="gemini-flash-lite-latest",
                input_tokens=900,
                output_tokens=120,
                succeeded=True,
                is_fallback=True,
            ),
        ],
        model_used="gemini-flash-lite-latest",
        used_fallback=True,
    )

    review, _ = run(pull_request, result)

    calls = list(LLMCall.objects.filter(review=review).order_by("id"))
    assert len(calls) == 2
    assert calls[0].succeeded is False and calls[0].error == "HTTP 429"
    assert calls[1].is_fallback is True
    assert review.used_fallback is True


@pytest.mark.django_db
def test_a_failed_review_is_recorded_not_raised(pull_request):
    result = agent_result(
        findings=[], succeeded=False, failure_reason="groq: failed after 3 attempts"
    )

    review, gh = run(pull_request, result)

    assert review.status == Review.Status.FAILED
    assert "failed after 3 attempts" in review.error
    # The user still gets told, in the PR.
    body = gh.update_issue_comment.call_args.args[3]
    assert "could not be completed" in body


@pytest.mark.django_db
def test_a_diff_fetch_failure_is_reported_in_the_comment(pull_request):
    with (
        mock.patch(
            "apps.reviews.services.fetch_diff",
            side_effect=services.DiffFetchError("HTTP 404"),
        ),
        mock.patch("apps.reviews.services.github_app") as gh,
    ):
        review = services.review_pull_request(pull_request, INSTALLATION_ID)

    assert review.status == Review.Status.FAILED
    body = gh.update_issue_comment.call_args.args[3]
    assert "HTTP 404" in body


@pytest.mark.django_db
def test_truncation_and_skips_are_persisted(pull_request):
    result = agent_result(truncated=True, skipped_files=["package-lock.json"])

    review, _ = run(pull_request, result)

    assert review.truncated is True
    assert review.skipped_files == ["package-lock.json"]


# ======================================================================== comment


@pytest.mark.django_db
def test_the_comment_is_edited_never_duplicated(pull_request):
    _, gh = run(pull_request, agent_result())

    gh.create_issue_comment.assert_not_called()
    # Once for "reviewing...", once for the result.
    assert gh.update_issue_comment.call_count == 2
    assert gh.update_issue_comment.call_args.args[2] == 4242


@pytest.mark.django_db
def test_a_missing_comment_is_created_once(pull_request):
    """Defensive: phase 2 always posts the ack, but the id could be lost."""
    pull_request.ack_comment_id = None
    pull_request.save()

    _, gh = run(pull_request, agent_result())

    assert gh.create_issue_comment.called
    pull_request.refresh_from_db()
    assert pull_request.ack_comment_id == 4242


@pytest.mark.django_db
def test_the_head_sha_appears_so_every_sync_is_a_visible_edit(pull_request):
    """GitHub no-ops a PATCH with a byte-identical body, so the body must change."""
    _, gh = run(pull_request, agent_result())

    body = gh.update_issue_comment.call_args.args[3]
    assert "abc1234" in body


@pytest.mark.django_db
def test_two_reviews_of_different_commits_produce_different_bodies(pull_request):
    _, first = run(pull_request, agent_result())
    first_body = first.update_issue_comment.call_args.args[3]

    pull_request.head_sha = "9999999aaaa"
    pull_request.save()
    _, second = run(pull_request, agent_result())
    second_body = second.update_issue_comment.call_args.args[3]

    assert first_body != second_body


@pytest.mark.django_db
def test_a_github_failure_does_not_lose_the_stored_review(pull_request):
    from apps.repos.github_app import GitHubAppError

    with (
        mock.patch("apps.reviews.services.fetch_diff", return_value=DIFF),
        mock.patch("apps.reviews.services.run_pipeline", return_value=agent_result()),
        mock.patch("apps.reviews.services.github_app") as gh,
    ):
        gh.update_issue_comment.side_effect = GitHubAppError("403")
        review = services.review_pull_request(pull_request, INSTALLATION_ID)

    assert review.status == Review.Status.DONE
    assert ReviewFinding.objects.filter(review=review).count() == 1


@pytest.mark.django_db
def test_findings_are_grouped_by_severity_in_the_comment(pull_request):
    result = agent_result(
        findings=[
            Finding("a.py", 1, Severity.BLOCKING, "correctness", "Serious problem."),
            Finding("b.py", 2, Severity.NIT, "style", "Minor thing."),
        ]
    )

    _, gh = run(pull_request, result)
    body = gh.update_issue_comment.call_args.args[3]

    assert "### Blocking" in body
    assert "### Nits" in body
    assert body.index("### Blocking") < body.index("### Nits")
    assert "1 blocking" in body


@pytest.mark.django_db
def test_a_clean_review_says_so(pull_request):
    _, gh = run(pull_request, agent_result(findings=[]))
    body = gh.update_issue_comment.call_args.args[3]

    assert "No issues found" in body


@pytest.mark.django_db
def test_truncation_is_disclosed_in_the_comment(pull_request):
    """A short review of a truncated diff must not look like a clean bill of health."""
    result = agent_result(findings=[], truncated=True, skipped_files=["big.py"])

    _, gh = run(pull_request, result)
    body = gh.update_issue_comment.call_args.args[3]

    assert "larger than the review budget" in body
    assert "big.py" in body


@pytest.mark.django_db
def test_many_skipped_files_are_summarised(pull_request):
    result = agent_result(skipped_files=[f"f{i}.lock" for i in range(15)])

    _, gh = run(pull_request, result)
    body = gh.update_issue_comment.call_args.args[3]

    assert "and 5 more" in body


@pytest.mark.django_db
def test_the_footer_carries_time_and_estimated_cost(pull_request):
    _, gh = run(pull_request, agent_result())
    body = gh.update_issue_comment.call_args.args[3]

    assert "Reviewed in" in body
    assert "at paid-tier rates" in body


@pytest.mark.django_db
def test_the_interim_comment_names_the_commit_being_reviewed(pull_request):
    _, gh = run(pull_request, agent_result())

    first_body = gh.update_issue_comment.call_args_list[0].args[3]
    assert "Reviewing" in first_body
    assert "abc1234" in first_body


def test_the_running_body_differs_from_the_ack_body():
    """Otherwise the first edit would be a no-op and the PR would look stuck."""
    assert comment_renderer.render_running("abc1234") != comment_renderer.ACK_BODY


# ========================================================================== task


@pytest.mark.django_db
def test_the_task_reviews_the_pull_request(pull_request):
    from apps.reviews.tasks import review_pull_request_task

    with mock.patch("apps.reviews.tasks.review_pull_request") as reviewer:
        reviewer.return_value = mock.Mock(pk=7, status="done")
        result = review_pull_request_task(pull_request.pk, INSTALLATION_ID)

    reviewer.assert_called_once()
    assert result == {"review_id": 7, "status": "done"}


@pytest.mark.django_db
def test_the_task_tolerates_a_deleted_pull_request():
    from apps.reviews.tasks import review_pull_request_task

    assert review_pull_request_task(999999, INSTALLATION_ID) is None


# =================================================================== config build


def test_the_config_is_built_from_settings(settings):
    settings.GROQ_API_KEY = "g"
    settings.REVIEW_PRIMARY_MODEL = "openai/gpt-oss-120b"
    settings.REVIEW_MAX_DIFF_BYTES = 1234

    config = services.build_config()

    assert config.groq_api_key == "g"
    assert config.primary_model == "openai/gpt-oss-120b"
    assert config.max_diff_bytes == 1234


# =================================================================== diff fetch


def test_the_diff_is_fetched_with_the_diff_media_type():
    response = mock.Mock(status_code=200)
    response.text = DIFF

    with (
        mock.patch(
            "apps.reviews.services.github_app.get_installation_token",
            return_value="ghs_x",
        ),
        mock.patch("apps.reviews.services.requests.get", return_value=response) as get,
    ):
        assert services.fetch_diff(1, "owner/repo", 1) == DIFF

    assert get.call_args.kwargs["headers"]["Accept"] == "application/vnd.github.v3.diff"


def test_a_diff_fetch_non_200_raises():
    with (
        mock.patch(
            "apps.reviews.services.github_app.get_installation_token",
            return_value="ghs_x",
        ),
        mock.patch(
            "apps.reviews.services.requests.get",
            return_value=mock.Mock(status_code=404),
        ),
    ):
        with pytest.raises(services.DiffFetchError, match="HTTP 404"):
            services.fetch_diff(1, "owner/repo", 1)


def test_a_diff_fetch_network_error_raises():
    import requests as requests_module

    with (
        mock.patch(
            "apps.reviews.services.github_app.get_installation_token",
            return_value="ghs_x",
        ),
        mock.patch(
            "apps.reviews.services.requests.get",
            side_effect=requests_module.ConnectionError("dns"),
        ),
    ):
        with pytest.raises(services.DiffFetchError, match="Could not reach GitHub"):
            services.fetch_diff(1, "owner/repo", 1)


# ================================================================ webhook wiring


@pytest.mark.django_db
def test_reopened_triggers_a_review():
    """A PR reopened after closure has had no review of this branch state."""
    from apps.repos.tasks import REVIEWABLE_ACTIONS

    assert REVIEWABLE_ACTIONS == {"opened", "synchronize", "reopened"}


@pytest.mark.django_db
def test_the_webhook_queues_a_review(pull_request):
    from apps.repos.models import WebhookEvent
    from apps.repos.tasks import handle_webhook_event

    payload = {
        "action": "opened",
        "pull_request": {
            "id": 1,
            "number": 1,
            "title": "Fix pagination",
            "state": "open",
            "user": {"login": "owner"},
            "head": {"sha": "abc1234def5678"},
            "base": {"ref": "main"},
        },
        "repository": {
            "id": 1,
            "full_name": "owner/repo",
            "name": "repo",
            "owner": {"login": "owner"},
            "default_branch": "main",
            "private": False,
        },
        "installation": {
            "id": INSTALLATION_ID,
            "account": {"login": "owner", "type": "User"},
        },
    }
    event = WebhookEvent.objects.create(
        delivery_id="d-review",
        event="pull_request",
        action="opened",
        payload=payload,
    )

    with (
        mock.patch("apps.repos.tasks.github_app.create_issue_comment", return_value={"id": 1}),
        mock.patch("apps.repos.tasks.github_app.update_issue_comment"),
        mock.patch("apps.reviews.tasks.review_pull_request_task.delay") as queued,
    ):
        handle_webhook_event(event.pk)

    queued.assert_called_once()


@pytest.mark.django_db
def test_a_broker_failure_does_not_lose_the_acknowledgement(pull_request):
    from apps.repos.models import WebhookEvent
    from apps.repos.tasks import handle_webhook_event

    payload = {
        "action": "opened",
        "pull_request": {
            "id": 1,
            "number": 1,
            "title": "x",
            "state": "open",
            "user": {"login": "owner"},
            "head": {"sha": "abc"},
            "base": {"ref": "main"},
        },
        "repository": {
            "id": 1,
            "full_name": "owner/repo",
            "name": "repo",
            "owner": {"login": "owner"},
            "default_branch": "main",
        },
        "installation": {"id": INSTALLATION_ID, "account": {"login": "owner"}},
    }
    event = WebhookEvent.objects.create(
        delivery_id="d-broker", event="pull_request", action="opened", payload=payload
    )

    with (
        mock.patch("apps.repos.tasks.github_app.create_issue_comment", return_value={"id": 9}),
        mock.patch("apps.repos.tasks.github_app.update_issue_comment"),
        mock.patch(
            "apps.reviews.tasks.review_pull_request_task.delay",
            side_effect=OSError("broker down"),
        ),
    ):
        handle_webhook_event(event.pk)  # must not raise

    event.refresh_from_db()
    assert event.processed_at is not None


# ====================================================================== str forms


@pytest.mark.django_db
def test_string_representations(pull_request):
    review, _ = run(pull_request, agent_result())
    finding = ReviewFinding.objects.get(review=review)
    call = LLMCall.objects.get(review=review)

    assert "owner/repo#1" in str(review)
    assert "app/users.py:13" in str(finding)
    assert "groq" in str(call)
    assert review.duration_seconds > 0


def test_findings_json_round_trip_is_not_needed_for_rendering():
    """Rendering reads attributes, so a plain object is enough for the renderer."""
    fake_review = mock.Mock(
        head_sha="abc1234",
        duration_ms=1000,
        estimated_cost_inr=Decimal("0.10"),
        model_used="m",
        used_fallback=False,
        truncated=False,
        skipped_files=[],
    )
    finding = mock.Mock(severity="blocking", category="correctness", file_path="a.py", line=1)
    finding.message = "Problem."

    body = comment_renderer.render(fake_review, [finding])

    assert "a.py:1" in body
    assert json.dumps({"ok": True})  # sanity: json import is used
