"""Small builders for the multi-tenant tests.

Phase 6's rule is that every endpoint is org-scoped and proven so by a cross-org
test, which means nearly every test needs two organisations with data in both.
These keep that setup to a line or two.
"""

from datetime import timedelta
from decimal import Decimal
from itertools import count

from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Membership
from apps.accounts.services import get_or_create_user_from_github
from apps.repos.models import AppInstallation, Repository
from apps.reviews.models import AgentRunRecord, PullRequest, Review, ReviewFinding

_ids = count(1000)


def user(login):
    """A user and their personal organisation, of which they are the owner."""
    created, _ = get_or_create_user_from_github(
        {"id": next(_ids), "login": login, "name": "", "email": "", "avatar_url": ""}
    )
    return created, created.memberships.get().organization


def add_member(person, organization, role=Membership.Role.MEMBER):
    return Membership.objects.create(user=person, organization=organization, role=role)


def access_token(person):
    return str(RefreshToken.for_user(person).access_token)


def client(person, organization=None):
    api = APIClient()
    headers = {"HTTP_AUTHORIZATION": f"Bearer {access_token(person)}"}
    if organization is not None:
        headers["HTTP_X_ORGANIZATION_ID"] = str(organization.pk)
    api.credentials(**headers)
    return api


def repository(organization, full_name=None):
    number = next(_ids)
    full_name = full_name or f"{organization.slug}/repo-{number}"
    installation = AppInstallation.objects.create(
        installation_id=number, account_login=full_name.split("/")[0], organization=organization
    )
    owner, name = full_name.split("/")
    return Repository.objects.create(
        organization=organization,
        installation=installation,
        github_id=number,
        full_name=full_name,
        owner=owner,
        name=name,
    )


def pull_request(repo, number=1, title="Change"):
    return PullRequest.objects.create(
        repository=repo, number=number, title=title, head_sha="abc1234def", ack_comment_id=99
    )


def review(
    pr,
    status=Review.Status.DONE,
    *,
    degraded=False,
    used_fallback=False,
    duration_ms=6000,
    cost_inr="0.0800",
    findings=(),
    days_ago=0,
    error="",
):
    """A review with findings given as (severity, category, agent) tuples."""
    row = Review.objects.create(
        pull_request=pr,
        status=status,
        head_sha=pr.head_sha,
        degraded=degraded,
        used_fallback=used_fallback,
        duration_ms=duration_ms,
        estimated_cost_inr=Decimal(cost_inr),
        model_used="openai/gpt-oss-120b",
        error=error,
    )
    if days_ago:
        Review.objects.filter(pk=row.pk).update(
            created_at=timezone.now() - timedelta(days=days_ago)
        )
        row.refresh_from_db()
    for line, (severity, category, agent) in enumerate(findings, start=1):
        ReviewFinding.objects.create(
            review=row,
            agent=agent,
            severity=severity,
            category=category,
            file_path="app/x.py",
            line=line * 10,
            message="Something.",
        )
    return row


def agent_run(review_row, name="security", **fields):
    return AgentRunRecord.objects.create(review=review_row, name=name, **fields)
