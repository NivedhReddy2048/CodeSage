"""Workspace selection and member role management (Phase 6a)."""

import pytest

from apps.accounts.models import Membership
from apps.audit.models import AuditLogEntry
from apps.repos.services import current_organization
from tests import factories


@pytest.fixture
def world(db):
    alice, org_a = factories.user("alice")
    bob, org_b = factories.user("bob")
    carol, _ = factories.user("carol")
    carol_in_a = factories.add_member(carol, org_a, Membership.Role.MEMBER)
    return locals()


# ------------------------------------------------------------ X-Organization-Id


def test_the_header_selects_an_organisation_the_caller_belongs_to(world):
    carol, org_a = world["carol"], world["org_a"]
    carol.requested_organization_id = org_a.pk

    assert current_organization(carol) == org_a


def test_the_header_naming_a_foreign_organisation_is_ignored(world):
    alice = world["alice"]
    alice.requested_organization_id = world["org_b"].pk

    assert current_organization(alice) == world["org_a"]


def test_the_header_reaches_the_api(world):
    """Carol, a member of Alice's org, switches to it and sees its member list."""
    response = factories.client(world["carol"], world["org_a"]).get("/api/orgs/members/")

    assert {m["user"]["github_login"] for m in response.data} == {"alice", "carol"}


@pytest.mark.parametrize("value", ["", "abc", "-4", "0"])
def test_a_garbage_header_falls_back(world, value):
    from rest_framework.test import APIClient

    api = APIClient()
    api.credentials(
        HTTP_AUTHORIZATION=f"Bearer {factories.access_token(world['carol'])}",
        HTTP_X_ORGANIZATION_ID=value,
    )
    logins = {m["user"]["github_login"] for m in api.get("/api/orgs/members/").data}

    assert logins == {"carol"}  # her personal organisation


# --------------------------------------------------------------------- members


def test_members_lists_only_the_current_organisation(world):
    response = factories.client(world["alice"]).get("/api/orgs/members/")

    assert {m["user"]["github_login"] for m in response.data} == {"alice", "carol"}
    assert "bob" not in str(response.data)


def test_an_owner_changes_a_role_and_it_is_audited(world):
    membership = world["carol_in_a"]

    response = factories.client(world["alice"]).patch(
        f"/api/orgs/members/{membership.pk}/", {"role": "admin"}, format="json"
    )

    assert response.status_code == 200
    membership.refresh_from_db()
    assert membership.role == "admin"
    entry = AuditLogEntry.objects.get(action="member.role_changed")
    assert entry.organization == world["org_a"]
    assert entry.actor == world["alice"]
    assert entry.target_label == "carol"
    assert entry.metadata == {"old_role": "member", "new_role": "admin"}


def test_an_admin_cannot_change_roles(world):
    world["carol_in_a"].role = Membership.Role.ADMIN
    world["carol_in_a"].save()
    alice_membership = world["alice"].memberships.get(organization=world["org_a"])

    response = factories.client(world["carol"], world["org_a"]).patch(
        f"/api/orgs/members/{alice_membership.pk}/", {"role": "member"}, format="json"
    )

    assert response.status_code == 403
    assert not AuditLogEntry.objects.exists()


def test_a_membership_in_another_organisation_is_not_found(world):
    bobs = world["bob"].memberships.get()

    response = factories.client(world["alice"]).patch(
        f"/api/orgs/members/{bobs.pk}/", {"role": "member"}, format="json"
    )

    assert response.status_code == 404
    bobs.refresh_from_db()
    assert bobs.role == "owner"


def test_the_last_owner_cannot_be_demoted(world):
    alice_membership = world["alice"].memberships.get(organization=world["org_a"])

    response = factories.client(world["alice"]).patch(
        f"/api/orgs/members/{alice_membership.pk}/", {"role": "member"}, format="json"
    )

    assert response.status_code == 400
    assert "at least one owner" in response.data["detail"]


def test_an_invalid_role_is_rejected(world):
    response = factories.client(world["alice"]).patch(
        f"/api/orgs/members/{world['carol_in_a'].pk}/", {"role": "superuser"}, format="json"
    )

    assert response.status_code == 400


def test_the_browser_may_send_the_workspace_header(client):
    """X-Organization-Id is not CORS-safelisted, so the browser preflights it. Without
    it in CORS_ALLOW_HEADERS every request from a chosen workspace failed before
    reaching Django - which the frontend took for an expired session and signed out."""
    response = client.options(
        "/api/auth/me/",
        HTTP_ORIGIN="http://localhost:3000",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,x-organization-id",
    )

    allowed = response.headers["Access-Control-Allow-Headers"].lower()
    assert "x-organization-id" in allowed
    assert "authorization" in allowed
