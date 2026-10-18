"""Tests for the repository management API.

The important assertions here are the boundaries: one tenant must never see or touch
another's repositories, and a plain member must not be able to rewire what the
organisation reviews.
"""

from unittest import mock

import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Membership, Organization
from apps.accounts.services import get_or_create_user_from_github
from apps.repos.github_app import GitHubAppError
from apps.repos.models import AppInstallation, Repository

INSTALLATION_ID = 172631969

TESTBED = {
    "id": 555000,
    "full_name": "NivedhReddy2048/codesage-testbed",
    "name": "codesage-testbed",
    "owner": {"login": "NivedhReddy2048"},
    "default_branch": "main",
    "private": False,
}
OTHER_REPO = {
    "id": 555001,
    "full_name": "NivedhReddy2048/portfolio",
    "name": "portfolio",
    "owner": {"login": "NivedhReddy2048"},
    "default_branch": "main",
    "private": True,
}


def make_user(github_id=181383619, login="NivedhReddy2048"):
    user, _ = get_or_create_user_from_github(
        {"id": github_id, "login": login, "name": "", "email": "", "avatar_url": ""}
    )
    return user


def auth(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def owner():
    return make_user()


@pytest.fixture
def installation():
    return AppInstallation.objects.create(
        installation_id=INSTALLATION_ID,
        account_login="NivedhReddy2048",
        account_type="User",
        repository_selection="selected",
    )


@pytest.fixture(autouse=True)
def app_slug(settings):
    # Avoids a GET /app round trip while building the install URL.
    settings.GITHUB_APP_SLUG = "codesage-nr"
    return settings


def mock_remote(*repos):
    return mock.patch(
        "apps.repos.views.github_app.list_installation_repositories",
        return_value=list(repos),
    )


# -------------------------------------------------------------------- auth required


@pytest.mark.django_db
@pytest.mark.parametrize(
    "name", ["repository-list", "repository-installable", "repository-connect"]
)
def test_endpoints_require_authentication(name):
    assert APIClient().get(reverse(name)).status_code == 401


# ------------------------------------------------------------------------ installable


@pytest.mark.django_db
def test_installable_reports_not_installed_without_an_installation(owner):
    response = auth(owner).get(reverse("repository-installable"))

    assert response.status_code == 200
    body = response.json()
    assert body["installed"] is False
    assert body["repositories"] == []
    # The user needs somewhere to go next.
    assert body["install_url"] == ("https://github.com/apps/codesage-nr/installations/new")


@pytest.mark.django_db
def test_installable_lists_repos_and_flags_connected(owner, installation):
    organization = owner.memberships.get().organization
    Repository.objects.create(
        organization=organization,
        installation=installation,
        github_id=TESTBED["id"],
        full_name=TESTBED["full_name"],
        owner="NivedhReddy2048",
        name="codesage-testbed",
    )

    with mock_remote(TESTBED, OTHER_REPO):
        response = auth(owner).get(reverse("repository-installable"))

    assert response.status_code == 200
    body = response.json()
    assert body["installed"] is True
    flags = {r["full_name"]: r["connected"] for r in body["repositories"]}
    assert flags == {
        "NivedhReddy2048/codesage-testbed": True,
        "NivedhReddy2048/portfolio": False,
    }


@pytest.mark.django_db
def test_installable_deduplicates_repos_seen_twice(owner, installation):
    """Two installations can expose the same repository."""
    AppInstallation.objects.create(installation_id=999, account_login="NivedhReddy2048")

    with mock_remote(TESTBED):
        response = auth(owner).get(reverse("repository-installable"))

    assert len(response.json()["repositories"]) == 1


@pytest.mark.django_db
def test_installable_survives_a_github_failure(owner, installation):
    """A GitHub outage should degrade the page, not 500 it."""
    with mock.patch(
        "apps.repos.views.github_app.list_installation_repositories",
        side_effect=GitHubAppError("503"),
    ):
        response = auth(owner).get(reverse("repository-installable"))

    assert response.status_code == 200
    assert response.json()["repositories"] == []


@pytest.mark.django_db
def test_installable_results_are_sorted(owner, installation):
    with mock_remote(OTHER_REPO, TESTBED):
        body = auth(owner).get(reverse("repository-installable")).json()

    names = [r["full_name"] for r in body["repositories"]]
    assert names == sorted(names)


# ---------------------------------------------------------------------------- connect


@pytest.mark.django_db
def test_connect_creates_the_repository_scoped_to_the_org(owner, installation):
    with mock_remote(TESTBED):
        response = auth(owner).post(
            reverse("repository-connect"), {"github_id": TESTBED["id"]}, format="json"
        )

    assert response.status_code == 201
    repository = Repository.objects.get()
    assert repository.organization == owner.memberships.get().organization
    assert repository.full_name == "NivedhReddy2048/codesage-testbed"
    assert repository.connected_by == owner
    assert repository.installation == installation


@pytest.mark.django_db
def test_connect_pins_the_installation_to_the_organization(owner, installation):
    """After connecting, the webhook path uses this link rather than login matching."""
    assert installation.organization_id is None

    with mock_remote(TESTBED):
        auth(owner).post(reverse("repository-connect"), {"github_id": TESTBED["id"]}, format="json")

    installation.refresh_from_db()
    assert installation.organization == owner.memberships.get().organization


@pytest.mark.django_db
def test_connecting_twice_is_idempotent(owner, installation):
    client = auth(owner)

    with mock_remote(TESTBED):
        first = client.post(
            reverse("repository-connect"), {"github_id": TESTBED["id"]}, format="json"
        )
        second = client.post(
            reverse("repository-connect"), {"github_id": TESTBED["id"]}, format="json"
        )

    assert first.status_code == 201
    assert second.status_code == 200
    assert Repository.objects.count() == 1


@pytest.mark.django_db
def test_cannot_connect_a_repo_the_installation_cannot_reach(owner, installation):
    """The posted id is checked against GitHub, not trusted."""
    with mock_remote(TESTBED):
        response = auth(owner).post(
            reverse("repository-connect"), {"github_id": 424242}, format="json"
        )

    assert response.status_code == 400
    assert "not available" in response.json()["detail"]
    assert Repository.objects.count() == 0


@pytest.mark.django_db
def test_connect_requires_a_github_id(owner, installation):
    response = auth(owner).post(reverse("repository-connect"), {}, format="json")

    assert response.status_code == 400


@pytest.mark.django_db
def test_connect_without_an_organization_is_rejected():
    """Defensive: signup always creates one, but the endpoint must not assume it."""
    from apps.accounts.models import User

    user = User.objects.create(username="orgless", github_login="nobody")

    response = auth(user).post(reverse("repository-connect"), {"github_id": 1}, format="json")

    assert response.status_code == 400


# -------------------------------------------------------------------------- RBAC


@pytest.mark.django_db
def test_a_member_cannot_connect(installation):
    """First real use of Membership.role: members look, admins rewire."""
    member = make_user(github_id=2, login="NivedhReddy2048")
    shared = Organization.objects.create(name="Shared", slug="shared")
    Membership.objects.filter(user=member).delete()
    Membership.objects.create(user=member, organization=shared, role=Membership.Role.MEMBER)

    with mock_remote(TESTBED):
        response = auth(member).post(
            reverse("repository-connect"), {"github_id": TESTBED["id"]}, format="json"
        )

    assert response.status_code == 403
    assert "owner or admin" in response.json()["detail"]
    assert Repository.objects.count() == 0


@pytest.mark.django_db
def test_an_admin_can_connect(installation):
    admin = make_user(github_id=3, login="NivedhReddy2048")
    shared = Organization.objects.create(name="Shared", slug="shared-admin")
    Membership.objects.filter(user=admin).delete()
    Membership.objects.create(user=admin, organization=shared, role=Membership.Role.ADMIN)

    with mock_remote(TESTBED):
        response = auth(admin).post(
            reverse("repository-connect"), {"github_id": TESTBED["id"]}, format="json"
        )

    assert response.status_code == 201


# ---------------------------------------------------------------------------- list


@pytest.mark.django_db
def test_list_shows_only_my_organizations_repositories(owner, installation):
    mine = owner.memberships.get().organization
    theirs = Organization.objects.create(name="Theirs", slug="theirs")

    Repository.objects.create(
        organization=mine,
        installation=installation,
        github_id=1,
        full_name="me/mine",
        owner="me",
        name="mine",
    )
    Repository.objects.create(
        organization=theirs,
        installation=installation,
        github_id=2,
        full_name="them/theirs",
        owner="them",
        name="theirs",
    )

    body = auth(owner).get(reverse("repository-list")).json()

    assert [r["full_name"] for r in body] == ["me/mine"]


@pytest.mark.django_db
def test_list_is_empty_without_an_organization():
    from apps.accounts.models import User

    user = User.objects.create(username="orgless2", github_login="nobody2")

    assert auth(user).get(reverse("repository-list")).json() == []


# ------------------------------------------------------------------------ disconnect


@pytest.mark.django_db
def test_disconnect_removes_the_repository(owner, installation):
    repository = Repository.objects.create(
        organization=owner.memberships.get().organization,
        installation=installation,
        github_id=1,
        full_name="me/mine",
        owner="me",
        name="mine",
    )

    response = auth(owner).delete(reverse("repository-detail", args=[repository.pk]))

    assert response.status_code == 204
    assert Repository.objects.count() == 0


@pytest.mark.django_db
def test_cannot_disconnect_another_organizations_repository(owner, installation):
    """Reads as 404, not 403: existence itself should not leak across tenants."""
    theirs = Organization.objects.create(name="Theirs", slug="theirs-2")
    repository = Repository.objects.create(
        organization=theirs,
        installation=installation,
        github_id=2,
        full_name="them/theirs",
        owner="them",
        name="theirs",
    )

    response = auth(owner).delete(reverse("repository-detail", args=[repository.pk]))

    assert response.status_code == 404
    assert Repository.objects.filter(pk=repository.pk).exists()


@pytest.mark.django_db
def test_a_member_cannot_disconnect(installation):
    member = make_user(github_id=4, login="NivedhReddy2048")
    shared = Organization.objects.create(name="Shared", slug="shared-del")
    Membership.objects.filter(user=member).delete()
    Membership.objects.create(user=member, organization=shared, role=Membership.Role.MEMBER)
    repository = Repository.objects.create(
        organization=shared,
        installation=installation,
        github_id=9,
        full_name="o/r",
        owner="o",
        name="r",
    )

    response = auth(member).delete(reverse("repository-detail", args=[repository.pk]))

    assert response.status_code == 403
    assert Repository.objects.filter(pk=repository.pk).exists()


@pytest.mark.django_db
def test_disconnecting_a_missing_repository_is_a_404(owner):
    assert auth(owner).delete(reverse("repository-detail", args=[999999])).status_code == 404


# ------------------------------------------------------------------- edge coverage


@pytest.mark.django_db
def test_install_url_is_fetched_from_github_when_not_configured(owner, settings):
    """The slug is cached for a day, so this is a cold-start cost only."""
    from django.core.cache import cache

    settings.GITHUB_APP_SLUG = ""
    cache.delete("github:app-slug")

    with mock.patch(
        "apps.repos.github_app.get_app_metadata", return_value={"slug": "fetched-slug"}
    ) as fetch:
        first = auth(owner).get(reverse("repository-installable")).json()
        second = auth(owner).get(reverse("repository-installable")).json()

    assert "fetched-slug" in first["install_url"]
    assert first["install_url"] == second["install_url"]
    # Cached: one network call for two requests.
    assert fetch.call_count == 1
    cache.delete("github:app-slug")


@pytest.mark.django_db
def test_install_url_degrades_when_the_app_credential_is_broken(owner, settings):
    """A broken App key must not stop the page rendering connected repos."""
    from django.core.cache import cache

    settings.GITHUB_APP_SLUG = ""
    cache.delete("github:app-slug")

    with mock.patch(
        "apps.repos.views.github_app.install_url", side_effect=GitHubAppError("no key")
    ):
        response = auth(owner).get(reverse("repository-installable"))

    assert response.status_code == 200
    assert response.json()["install_url"] == ""


@pytest.mark.django_db
def test_an_empty_slug_yields_no_install_url(settings):
    from django.core.cache import cache

    from apps.repos import github_app

    settings.GITHUB_APP_SLUG = ""
    cache.delete("github:app-slug")

    with mock.patch("apps.repos.github_app.get_app_metadata", return_value={}):
        assert github_app.install_url() == ""

    cache.delete("github:app-slug")


@pytest.mark.django_db
def test_connect_skips_an_installation_github_cannot_list(owner, installation):
    """One failing installation must not block connecting via another."""
    AppInstallation.objects.create(installation_id=888, account_login="NivedhReddy2048")

    with mock.patch(
        "apps.repos.views.github_app.list_installation_repositories",
        side_effect=[GitHubAppError("503"), [TESTBED]],
    ):
        response = auth(owner).post(
            reverse("repository-connect"), {"github_id": TESTBED["id"]}, format="json"
        )

    assert response.status_code == 201


@pytest.mark.django_db
def test_role_in_without_an_organization_is_none():
    from apps.repos import services

    user = make_user(github_id=50, login="x")

    assert services.role_in(user, None) is None


@pytest.mark.django_db
def test_a_non_member_is_refused():
    """Not a member at all, as distinct from being a member without the role."""
    from apps.repos import services

    user = make_user(github_id=51, login="y")
    other = Organization.objects.create(name="Not mine", slug="not-mine")

    with pytest.raises(services.PermissionDenied, match="not a member"):
        services.require_management_role(user, other)
