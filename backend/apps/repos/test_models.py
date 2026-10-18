"""Model tests for the repos app: tenancy scoping and webhook idempotency."""

import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import Organization
from apps.accounts.services import get_or_create_user_from_github
from apps.repos.models import AppInstallation, Repository, WebhookEvent


@pytest.fixture
def org():
    user, _ = get_or_create_user_from_github(
        {"id": 1, "login": "owner", "name": "", "email": "", "avatar_url": ""}
    )
    return user.memberships.get().organization


@pytest.fixture
def installation():
    return AppInstallation.objects.create(
        installation_id=172631969,
        account_login="NivedhReddy2048",
        account_type="User",
        repository_selection=AppInstallation.RepositorySelection.SELECTED,
    )


@pytest.mark.django_db
def test_installation_id_is_unique():
    """GitHub's installation id is the natural key; duplicates would split state."""
    AppInstallation.objects.create(installation_id=1, account_login="a")

    with pytest.raises(IntegrityError), transaction.atomic():
        AppInstallation.objects.create(installation_id=1, account_login="b")


@pytest.mark.django_db
def test_installation_may_exist_before_being_linked_to_an_organization():
    """GitHub can deliver an installation webhook before anyone connects a repo."""
    inst = AppInstallation.objects.create(installation_id=2, account_login="a")

    assert inst.organization is None


@pytest.mark.django_db
def test_a_repo_cannot_be_connected_twice_to_the_same_org(org, installation):
    Repository.objects.create(
        organization=org,
        installation=installation,
        github_id=555,
        full_name="NivedhReddy2048/codesage-testbed",
        owner="NivedhReddy2048",
        name="codesage-testbed",
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        Repository.objects.create(
            organization=org,
            installation=installation,
            github_id=555,
            full_name="NivedhReddy2048/codesage-testbed",
            owner="NivedhReddy2048",
            name="codesage-testbed",
        )


@pytest.mark.django_db
def test_the_same_repo_can_be_connected_by_two_different_orgs(org, installation):
    """Scoping is per tenant: a public repo may legitimately interest two orgs."""
    other = Organization.objects.create(name="Other", slug="other")

    for organization in (org, other):
        Repository.objects.create(
            organization=organization,
            installation=installation,
            github_id=777,
            full_name="octocat/hello",
            owner="octocat",
            name="hello",
        )

    assert Repository.objects.filter(github_id=777).count() == 2


@pytest.mark.django_db
def test_deleting_an_installation_keeps_the_repository_row(org, installation):
    """Uninstalling the App should not erase the audit trail of what was connected."""
    repo = Repository.objects.create(
        organization=org,
        installation=installation,
        github_id=1,
        full_name="o/r",
        owner="o",
        name="r",
    )

    installation.delete()
    repo.refresh_from_db()

    assert repo.installation is None
    assert Repository.objects.filter(pk=repo.pk).exists()


@pytest.mark.django_db
def test_deleting_an_organization_removes_its_repositories(org, installation):
    """Tenant data must not outlive the tenant."""
    Repository.objects.create(
        organization=org,
        installation=installation,
        github_id=1,
        full_name="o/r",
        owner="o",
        name="r",
    )

    org.delete()

    assert Repository.objects.count() == 0


@pytest.mark.django_db
def test_delivery_id_is_unique():
    """This constraint is what makes webhook redelivery idempotent.

    GitHub reuses the delivery id on a manual redelivery, so a second insert collides
    instead of queueing a duplicate review.
    """
    WebhookEvent.objects.create(delivery_id="abc-123", event="pull_request", payload={})

    with pytest.raises(IntegrityError), transaction.atomic():
        WebhookEvent.objects.create(delivery_id="abc-123", event="pull_request", payload={})


@pytest.mark.django_db
def test_webhook_event_starts_unprocessed():
    """An unprocessed row is findable after a crash, which is the point of storing it."""
    event = WebhookEvent.objects.create(
        delivery_id="d1", event="pull_request", action="opened", payload={"a": 1}
    )

    assert event.processed_at is None
    assert event.received_at is not None


@pytest.mark.django_db
def test_webhook_payload_round_trips_as_json():
    payload = {"action": "opened", "number": 42, "nested": {"list": [1, 2, 3]}}

    event = WebhookEvent.objects.create(delivery_id="d2", event="pull_request", payload=payload)
    event.refresh_from_db()

    assert event.payload == payload


@pytest.mark.django_db
def test_str_representations(org, installation):
    repo = Repository.objects.create(
        organization=org,
        installation=installation,
        github_id=1,
        full_name="o/r",
        owner="o",
        name="r",
    )
    event = WebhookEvent.objects.create(
        delivery_id="d3", event="pull_request", action="opened", payload={}
    )
    bare = WebhookEvent.objects.create(delivery_id="d4", event="ping", payload={})

    assert str(repo) == "o/r"
    assert "172631969" in str(installation)
    assert str(event) == "pull_request.opened (d3)"
    assert str(bare) == "ping (d4)"
