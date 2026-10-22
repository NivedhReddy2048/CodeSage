"""Refresh tokens are single-use, sign-out revokes them, and auth events are audited.

Before this, ROTATE_REFRESH_TOKENS rotated tokens without blacklisting the old ones:
a rotated refresh token replayed against the live backend got 200, and sign-out
(client-only) left a copied refresh token valid for its full seven days.
"""

from unittest import mock

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.github import GitHubOAuthError
from apps.audit.models import AuditLogEntry
from tests import factories

PROFILE = {
    "id": 4242,
    "login": "octocat",
    "name": "Mona Lisa",
    "email": "octocat@example.com",
    "avatar_url": "",
}


def refresh(client, token):
    return client.post(reverse("token-refresh"), {"refresh": token}, format="json")


def sign_in(client, **extra):
    state = client.get(reverse("github-start")).json()["state"]
    with (
        mock.patch("apps.accounts.github.exchange_code_for_token", return_value="gho_fake"),
        mock.patch("apps.accounts.github.fetch_user_profile", return_value=PROFILE),
    ):
        response = client.post(
            reverse("github-callback"), {"code": "abc", "state": state}, format="json", **extra
        )
    assert response.status_code == 200
    return response.json()


def entries(action):
    return list(AuditLogEntry.objects.filter(action=action))


# --------------------------------------------------------------------- blacklist


@pytest.mark.django_db
def test_a_rotated_refresh_token_cannot_be_used_again():
    client = APIClient()
    first = sign_in(client)["refresh"]

    rotated = refresh(client, first)
    replayed = refresh(client, first)

    assert rotated.status_code == 200
    assert rotated.json()["refresh"] != first
    assert replayed.status_code == 401
    # And the new one works.
    assert refresh(client, rotated.json()["refresh"]).status_code == 200


@pytest.mark.django_db
def test_a_refresh_after_sign_out_is_refused():
    client = APIClient()
    token = sign_in(client)["refresh"]

    out = client.post(reverse("logout"), {"refresh": token}, format="json")

    assert out.status_code == 204
    assert refresh(client, token).status_code == 401


@pytest.mark.django_db
@pytest.mark.parametrize("token", ["", "not-a-jwt"])
def test_sign_out_with_nothing_to_revoke_is_still_204_and_audits_nothing(token):
    client = APIClient()

    assert client.post(reverse("logout"), {"refresh": token}, format="json").status_code == 204
    assert AuditLogEntry.objects.count() == 0


@pytest.mark.django_db
def test_signing_out_twice_audits_once():
    client = APIClient()
    token = sign_in(client)["refresh"]

    client.post(reverse("logout"), {"refresh": token}, format="json")
    second = client.post(reverse("logout"), {"refresh": token}, format="json")

    assert second.status_code == 204
    assert len(entries("auth.signed_out")) == 1


# ------------------------------------------------------------------- audit trail


@pytest.mark.django_db
def test_a_sign_in_is_audited_in_the_users_organisation_with_the_ip():
    client = APIClient()
    sign_in(client, HTTP_X_FORWARDED_FOR="203.0.113.7, 10.0.0.1", HTTP_USER_AGENT="Edge")

    (entry,) = entries("auth.signed_in")
    assert entry.actor.github_login == "octocat"
    assert entry.organization == entry.actor.memberships.get().organization
    assert entry.metadata["ip"] == "203.0.113.7"  # the client, not the proxy
    assert entry.metadata["user_agent"] == "Edge"
    assert entry.metadata["first_sign_in"] is True
    assert entry.created_at is not None


@pytest.mark.django_db
def test_a_sign_in_is_filed_under_every_organisation_the_user_belongs_to():
    client = APIClient()
    sign_in(client)
    first = entries("auth.signed_in")[0]
    user, personal = first.actor, first.organization
    _, team = factories.user("teamowner")
    factories.add_member(user, team)

    sign_in(client)

    second_round = AuditLogEntry.objects.filter(action="auth.signed_in").order_by("-id")[:2]
    assert {entry.organization for entry in second_round} == {personal, team}


@pytest.mark.django_db
def test_a_sign_out_is_audited():
    client = APIClient()
    token = sign_in(client)["refresh"]

    client.post(reverse("logout"), {"refresh": token}, format="json", REMOTE_ADDR="198.51.100.4")

    (entry,) = entries("auth.signed_out")
    assert entry.actor_login == "octocat"
    assert entry.metadata["ip"] == "198.51.100.4"


@pytest.mark.django_db
def test_a_failed_oauth_sign_in_is_audited_without_an_organisation():
    client = APIClient()
    state = client.get(reverse("github-start")).json()["state"]

    with mock.patch(
        "apps.accounts.github.exchange_code_for_token",
        side_effect=GitHubOAuthError("The code has expired"),
    ):
        response = client.post(
            reverse("github-callback"), {"code": "old", "state": state}, format="json"
        )

    assert response.status_code == 400
    (entry,) = entries("auth.sign_in_failed")
    assert (entry.organization, entry.actor) == (None, None)
    assert entry.metadata["reason"] == "The code has expired"


@pytest.mark.django_db
def test_replaying_a_revoked_refresh_token_is_audited_as_a_failed_sign_in():
    """Someone kept a copy: the owner's workspaces should know."""
    client = APIClient()
    token = sign_in(client)["refresh"]
    refresh(client, token)  # rotated, so `token` is now blacklisted

    assert refresh(client, token).status_code == 401

    (entry,) = entries("auth.sign_in_failed")
    assert entry.actor_login == "octocat"
    assert entry.organization is not None
    assert entry.metadata["reason"] == "revoked refresh token presented again"


@pytest.mark.django_db
def test_a_garbage_refresh_token_is_refused_without_an_audit_entry():
    assert refresh(APIClient(), "garbage").status_code == 401
    assert entries("auth.sign_in_failed") == []


@pytest.mark.django_db
def test_the_auth_filter_lists_every_auth_event_and_nothing_else():
    client = APIClient()
    token = sign_in(client)["refresh"]
    client.post(reverse("logout"), {"refresh": token}, format="json")
    owner = entries("auth.signed_in")[0].actor
    AuditLogEntry.objects.create(
        organization=owner.memberships.get().organization,
        actor=owner,
        action="repo.connected",
    )

    listed = factories.client(owner).get("/api/audit-log/?action=auth").json()["results"]

    assert sorted(row["action"] for row in listed) == ["auth.signed_in", "auth.signed_out"]
    assert {row["action_label"] for row in listed} == {"Signed in", "Signed out"}
