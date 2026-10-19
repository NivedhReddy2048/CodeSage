"""The rerun_review and retrieval_probe management commands."""

from io import StringIO
from types import SimpleNamespace
from unittest import mock

import pytest
from django.core.management import CommandError, call_command

from apps.repos.models import WebhookEvent
from apps.reviews.models import AgentRunRecord, PullRequest, Review
from apps.reviews.test_degraded import pull_request  # noqa: F401 - fixture reuse

PR_DATA = {
    "id": 555,
    "title": "Paginate users",
    "user": {"login": "author"},
    "head": {"sha": "fffffff1234567"},
    "base": {"ref": "main"},
    "state": "open",
}


def fake_review(pr, installation_id):
    review = Review.objects.create(
        pull_request=pr,
        status=Review.Status.DONE,
        head_sha=pr.head_sha,
        model_used="gemini-flash-lite-latest",
        used_fallback=True,
    )
    AgentRunRecord.objects.create(
        review=review,
        name="security",
        model="gemini-flash-lite-latest",
        requested_model="openai/gpt-oss-120b",
        provider="gemini",
        used_fallback=True,
        succeeded=True,
    )
    return review


@pytest.mark.django_db
def test_rerun_review_refreshes_the_head_and_reviews_synchronously(pull_request):  # noqa: F811
    out = StringIO()
    with (
        mock.patch(
            "apps.reviews.management.commands.rerun_review.github_app.get_pull_request",
            return_value=PR_DATA,
        ),
        mock.patch(
            "apps.reviews.management.commands.rerun_review.review_pull_request",
            side_effect=fake_review,
        ) as review,
    ):
        call_command("rerun_review", "owner/repo", "1", stdout=out)

    pull_request.refresh_from_db()
    assert pull_request.head_sha == "fffffff1234567"
    assert review.call_args.args == (pull_request, 1)
    text = out.getvalue()
    assert "fallback for openai/gpt-oss-120b" in text
    assert "https://github.com/owner/repo/pull/1/files" in text
    assert "#issuecomment-99" in text


@pytest.mark.django_db
def test_rerun_review_bypasses_delivery_dedupe(pull_request):  # noqa: F811
    """A delivery already processed blocks a webhook replay, not this command."""
    WebhookEvent.objects.create(
        delivery_id="already-seen", event="pull_request", action="opened", payload={}
    )
    with (
        mock.patch(
            "apps.reviews.management.commands.rerun_review.github_app.get_pull_request",
            return_value=PR_DATA,
        ),
        mock.patch(
            "apps.reviews.management.commands.rerun_review.review_pull_request",
            side_effect=fake_review,
        ) as review,
    ):
        call_command("rerun_review", "owner/repo", "1", stdout=StringIO())
        call_command("rerun_review", "owner/repo", "1", stdout=StringIO())

    assert review.call_count == 2
    assert WebhookEvent.objects.count() == 1


@pytest.mark.django_db
def test_rerun_review_creates_a_pr_record_it_has_not_seen(pull_request):  # noqa: F811
    with (
        mock.patch(
            "apps.reviews.management.commands.rerun_review.github_app.get_pull_request",
            return_value=PR_DATA,
        ),
        mock.patch(
            "apps.reviews.management.commands.rerun_review.review_pull_request",
            side_effect=fake_review,
        ),
    ):
        call_command("rerun_review", "owner/repo", "7", stdout=StringIO())

    assert PullRequest.objects.get(number=7).title == "Paginate users"


@pytest.mark.django_db
def test_rerun_review_rejects_an_unknown_repository():
    with pytest.raises(CommandError, match="No connected repository"):
        call_command("rerun_review", "nobody/nothing", "1", stdout=StringIO())


@pytest.mark.django_db
def test_retrieval_probe_shows_both_rankings(pull_request):  # noqa: F811
    module = "apps.ingestion.management.commands.retrieval_probe"
    docstring = SimpleNamespace(
        pk=1, file_path="app/users.py", line_start=1, line_end=5, symbol="", distance=0.26
    )
    find_by_id = SimpleNamespace(
        pk=2,
        file_path="app/users.py",
        line_start=15,
        line_end=20,
        symbol="UserRepository.find_by_id",
        distance=0.31,
    )
    out = StringIO()
    with (
        mock.patch(f"{module}.embed_query", return_value=[0.1]),
        mock.patch(f"{module}.vector_search", return_value=[docstring, find_by_id]),
        mock.patch(f"{module}.text_search", return_value=[find_by_id]),
        mock.patch(f"{module}.hybrid_search", return_value=[(find_by_id, 0.03), (docstring, 0.02)]),
    ):
        call_command("retrieval_probe", "look up a user", "--repo", "owner/repo", stdout=out)

    text = out.getvalue()
    assert "1. app/users.py:1-5 (module)" in text
    assert "1. app/users.py:15-20 UserRepository.find_by_id" in text
    assert "(vector rank 2, text rank 1)" in text


@pytest.mark.django_db
def test_retrieval_probe_needs_a_repo_when_none_is_indexed():
    with pytest.raises(CommandError, match="Pass --repo"):
        call_command("retrieval_probe", "anything", stdout=StringIO())
