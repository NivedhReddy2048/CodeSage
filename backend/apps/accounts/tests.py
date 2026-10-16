"""Phase 1a auth tests.

GitHub is always mocked: these tests must not make network calls, and must not burn
OAuth rate limit in CI.
"""

from unittest import mock
from urllib.parse import parse_qs, urlparse

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.github import GitHubOAuthError
from apps.accounts.models import Membership, Organization, User
from apps.accounts.services import get_or_create_user_from_github

PROFILE = {
    "id": 4242,
    "login": "octocat",
    "name": "Mona Lisa Octocat",
    "email": "octocat@example.com",
    "avatar_url": "https://avatars.githubusercontent.com/u/4242",
}


@pytest.fixture
def client():
    return APIClient()


def authenticate(client, user):
    """Attach a real JWT for `user`, exercising the same path the frontend uses."""
    from rest_framework_simplejwt.tokens import RefreshToken

    token = RefreshToken.for_user(user).access_token
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


# --------------------------------------------------------------------------- start


def test_start_returns_authorize_url_and_state(client, settings):
    settings.GITHUB_CLIENT_ID = "test-client-id"

    response = client.get(reverse("github-start"))

    assert response.status_code == 200
    body = response.json()
    assert body["state"]

    url = urlparse(body["authorize_url"])
    params = parse_qs(url.query)

    assert url.netloc == "github.com"
    assert url.path == "/login/oauth/authorize"
    assert params["client_id"] == ["test-client-id"]
    # The state must travel in the URL, or GitHub will not echo it back. Compare the
    # decoded parameter: the signed value contains ":" separators, which are
    # percent-encoded in the query string.
    assert params["state"] == [body["state"]]
    assert params["redirect_uri"] == [settings.GITHUB_OAUTH_REDIRECT_URI]
    assert "read:user" in params["scope"][0]


def test_start_is_public(client):
    """Login cannot require being logged in."""
    assert client.get(reverse("github-start")).status_code == 200


# ------------------------------------------------------------------------ callback


@pytest.mark.django_db
def test_callback_creates_user_and_personal_org(client):
    state = client.get(reverse("github-start")).json()["state"]

    with (
        mock.patch("apps.accounts.github.exchange_code_for_token", return_value="gho_fake"),
        mock.patch("apps.accounts.github.fetch_user_profile", return_value=PROFILE),
    ):
        response = client.post(reverse("github-callback"), {"code": "abc123", "state": state})

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["access"] and body["refresh"]
    assert body["user"]["github_login"] == "octocat"

    user = User.objects.get(github_id=4242)
    assert user.username == "octocat"
    assert user.email == "octocat@example.com"
    assert user.first_name == "Mona"
    assert not user.has_usable_password()

    membership = Membership.objects.get(user=user)
    assert membership.role == Membership.Role.OWNER
    assert membership.organization.is_personal is True


@pytest.mark.django_db
def test_callback_matches_existing_user_without_creating_second_org(client):
    """A second login must reuse the account, not duplicate it."""
    get_or_create_user_from_github(PROFILE)
    assert Organization.objects.count() == 1

    state = client.get(reverse("github-start")).json()["state"]
    with (
        mock.patch("apps.accounts.github.exchange_code_for_token", return_value="gho_fake"),
        mock.patch("apps.accounts.github.fetch_user_profile", return_value=PROFILE),
    ):
        response = client.post(reverse("github-callback"), {"code": "abc123", "state": state})

    assert response.status_code == 200
    assert response.json()["created"] is False
    assert User.objects.count() == 1
    assert Organization.objects.count() == 1


@pytest.mark.django_db
def test_callback_matches_on_github_id_after_a_rename(client):
    """GitHub logins can be renamed; the numeric id is the stable identity."""
    user, _ = get_or_create_user_from_github(PROFILE)

    renamed = {**PROFILE, "login": "monalisa"}
    user, created = get_or_create_user_from_github(renamed)

    assert created is False
    assert User.objects.count() == 1
    user.refresh_from_db()
    assert user.github_login == "monalisa"


@pytest.mark.django_db
def test_callback_rejects_tampered_state(client):
    with mock.patch(
        "apps.accounts.github.exchange_code_for_token", return_value="gho_fake"
    ) as exchange:
        response = client.post(
            reverse("github-callback"), {"code": "abc123", "state": "not-a-real-state"}
        )

    assert response.status_code == 400
    # The code must never be exchanged when state fails: that is the CSRF guard.
    exchange.assert_not_called()
    assert User.objects.count() == 0


@pytest.mark.django_db
def test_callback_surfaces_github_rejection_as_400(client):
    state = client.get(reverse("github-start")).json()["state"]

    with mock.patch(
        "apps.accounts.github.exchange_code_for_token",
        side_effect=GitHubOAuthError("bad_verification_code"),
    ):
        response = client.post(reverse("github-callback"), {"code": "stale", "state": state})

    assert response.status_code == 400
    assert "bad_verification_code" in response.json()["detail"]
    assert User.objects.count() == 0


@pytest.mark.django_db
def test_callback_requires_code_and_state(client):
    response = client.post(reverse("github-callback"), {})
    assert response.status_code == 400


# ------------------------------------------------------------- protected endpoints


@pytest.mark.django_db
def test_orgs_requires_authentication(client):
    assert client.get(reverse("organization-list")).status_code == 401


@pytest.mark.django_db
def test_orgs_rejects_a_garbage_token(client):
    client.credentials(HTTP_AUTHORIZATION="Bearer not-a-jwt")
    assert client.get(reverse("organization-list")).status_code == 401


@pytest.mark.django_db
def test_orgs_lists_only_my_orgs_with_my_role(client):
    mine, _ = get_or_create_user_from_github(PROFILE)
    # A second user with their own personal org, which must not leak into my list.
    get_or_create_user_from_github({**PROFILE, "id": 99, "login": "someone-else"})

    response = authenticate(client, mine).get(reverse("organization-list"))

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["role"] == "owner"
    assert body[0]["is_personal"] is True


@pytest.mark.django_db
def test_current_user_endpoint_returns_me(client):
    user, _ = get_or_create_user_from_github(PROFILE)

    response = authenticate(client, user).get(reverse("current-user"))

    assert response.status_code == 200
    assert response.json()["github_login"] == "octocat"


@pytest.mark.django_db
def test_refresh_endpoint_issues_a_new_access_token(client):
    user, _ = get_or_create_user_from_github(PROFILE)
    from rest_framework_simplejwt.tokens import RefreshToken

    refresh = str(RefreshToken.for_user(user))

    response = client.post(reverse("token-refresh"), {"refresh": refresh})

    assert response.status_code == 200
    assert response.json()["access"]


# ------------------------------------------------------------------------ services


@pytest.mark.django_db
def test_slug_collisions_are_resolved():
    get_or_create_user_from_github(PROFILE)
    get_or_create_user_from_github({**PROFILE, "id": 777})

    slugs = list(Organization.objects.values_list("slug", flat=True))
    assert len(slugs) == len(set(slugs)), "organisation slugs must stay unique"


@pytest.mark.django_db
def test_missing_email_is_tolerated():
    """GitHub hides emails by default; login must still work."""
    user, created = get_or_create_user_from_github(
        {"id": 5, "login": "private-person", "avatar_url": "", "name": ""}
    )

    assert created is True
    assert user.email == ""
    assert Membership.objects.filter(user=user, role="owner").exists()
