"""Push-event filtering and the review API.

Push filtering matters because indexing is the one thing that spends Gemini quota,
and a push webhook fires for every branch and tag in the repository.
"""

from unittest import mock

import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Organization
from apps.accounts.services import get_or_create_user_from_github
from apps.repos.models import AppInstallation, Repository, WebhookEvent
from apps.repos.tasks import handle_webhook_event
from apps.reviews.models import LLMCall, PullRequest, Review, ReviewFinding

INSTALLATION_ID = 172631969
REPO_GITHUB_ID = 555000


def make_user(github_id=1, login="owner"):
    user, _ = get_or_create_user_from_github(
        {"id": github_id, "login": login, "name": "", "email": "", "avatar_url": ""}
    )
    return user


def auth(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def owner(db):
    return make_user()


@pytest.fixture
def repository(owner):
    installation = AppInstallation.objects.create(
        installation_id=INSTALLATION_ID, account_login="owner"
    )
    return Repository.objects.create(
        organization=owner.memberships.get().organization,
        installation=installation,
        github_id=REPO_GITHUB_ID,
        full_name="owner/repo",
        owner="owner",
        name="repo",
        default_branch="main",
    )


def push_payload(
    ref="refs/heads/main", default_branch="main", github_id=REPO_GITHUB_ID, deleted=False
):
    return {
        "ref": ref,
        "deleted": deleted,
        "after": "abc1234",
        "repository": {
            "id": github_id,
            "full_name": "owner/repo",
            "name": "repo",
            "owner": {"login": "owner"},
            "default_branch": default_branch,
        },
        "installation": {"id": INSTALLATION_ID, "account": {"login": "owner"}},
    }


def deliver_push(payload, delivery="push-1"):
    event = WebhookEvent.objects.create(
        delivery_id=delivery,
        event="push",
        action="",
        installation_id=INSTALLATION_ID,
        repository_full_name="owner/repo",
        payload=payload,
    )
    with mock.patch("apps.ingestion.services.start_ingestion") as start:
        start.return_value = (mock.Mock(pk=1), True)
        handle_webhook_event(event.pk)
    return start, event


# ================================================================ push filtering


@pytest.mark.django_db
def test_a_push_to_the_default_branch_reindexes(repository):
    start, event = deliver_push(push_payload())

    start.assert_called_once()
    assert start.call_args.args[0] == repository
    event.refresh_from_db()
    assert event.processed_at is not None


@pytest.mark.django_db
def test_a_push_to_another_branch_is_ignored(repository):
    """Feature-branch code is not what retrieval answers from."""
    start, _ = deliver_push(push_payload(ref="refs/heads/feature/x"))

    start.assert_not_called()


@pytest.mark.django_db
def test_a_tag_push_is_ignored(repository):
    start, _ = deliver_push(push_payload(ref="refs/tags/v1.0.0"))

    start.assert_not_called()


@pytest.mark.django_db
def test_a_branch_deletion_is_ignored(repository):
    start, _ = deliver_push(push_payload(deleted=True))

    start.assert_not_called()


@pytest.mark.django_db
def test_a_push_to_an_unconnected_repository_is_ignored(owner):
    """An installation can see repositories nobody connected; not ours to index."""
    start, _ = deliver_push(push_payload(github_id=999999))

    start.assert_not_called()


@pytest.mark.django_db
def test_a_push_with_a_different_default_branch_is_respected(repository):
    """Repos whose default is `master` must still work."""
    repository.default_branch = "master"
    repository.save()

    start, _ = deliver_push(push_payload(ref="refs/heads/master", default_branch="master"))

    start.assert_called_once()


@pytest.mark.django_db
def test_a_malformed_push_payload_does_not_crash(repository):
    start, event = deliver_push({"ref": "refs/heads/main"})

    start.assert_not_called()
    event.refresh_from_db()
    assert event.processed_at is not None


@pytest.mark.django_db
def test_a_push_does_not_create_a_review(repository):
    """Pushes re-index; they do not review. Reviews come from pull_request events."""
    deliver_push(push_payload())

    assert Review.objects.count() == 0


# ==================================================================== review API


@pytest.fixture
def review(repository):
    pull_request = PullRequest.objects.create(
        repository=repository, number=1, title="Fix pagination", head_sha="abc1234"
    )
    review = Review.objects.create(
        pull_request=pull_request,
        status=Review.Status.DONE,
        head_sha="abc1234",
        model_used="openai/gpt-oss-120b",
        total_input_tokens=1000,
        total_output_tokens=200,
        duration_ms=3400,
        estimated_cost_inr="0.0400",
    )
    ReviewFinding.objects.create(
        review=review,
        severity="blocking",
        category="correctness",
        file_path="app/users.py",
        line=13,
        message="Off-by-one.",
    )
    LLMCall.objects.create(
        review=review,
        provider="groq",
        model="openai/gpt-oss-120b",
        input_tokens=1000,
        output_tokens=200,
        latency_ms=3300,
        succeeded=True,
    )
    return review


@pytest.mark.django_db
def test_review_detail_requires_authentication(review):
    assert APIClient().get(reverse("review-detail", args=[review.pk])).status_code == 401


@pytest.mark.django_db
def test_review_detail_returns_findings_and_telemetry(owner, review):
    response = auth(owner).get(reverse("review-detail", args=[review.pk]))

    assert response.status_code == 200
    body = response.json()
    assert body["repository"] == "owner/repo"
    assert body["pr_number"] == 1
    assert body["model_used"] == "openai/gpt-oss-120b"
    assert len(body["findings"]) == 1
    assert body["findings"][0]["file_path"] == "app/users.py"
    assert len(body["calls"]) == 1
    assert body["calls"][0]["provider"] == "groq"


@pytest.mark.django_db
def test_another_organizations_review_is_a_404(review):
    outsider = make_user(github_id=2, login="outsider")
    Organization.objects.create(name="Theirs", slug="theirs")

    response = auth(outsider).get(reverse("review-detail", args=[review.pk]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_a_missing_review_is_a_404(owner):
    assert auth(owner).get(reverse("review-detail", args=[999999])).status_code == 404


@pytest.mark.django_db
def test_repository_reviews_are_listed(owner, repository, review):
    response = auth(owner).get(reverse("repository-review-list", args=[repository.pk]))

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["finding_count"] == 1
    assert body[0]["pr_number"] == 1


@pytest.mark.django_db
def test_another_organizations_repository_lists_nothing(repository, review):
    outsider = make_user(github_id=3, login="nobody")

    response = auth(outsider).get(reverse("repository-review-list", args=[repository.pk]))

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.django_db
def test_a_user_without_an_organization_sees_nothing(review):
    from apps.accounts.models import User

    user = User.objects.create(username="orgless", github_login="orgless")

    assert auth(user).get(reverse("review-detail", args=[review.pk])).status_code == 404
