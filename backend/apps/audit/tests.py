"""The audit log: append-only, org-scoped, and fed by the actions that matter."""

from unittest import mock

import pytest

from apps.accounts.models import Membership
from apps.audit.models import AppendOnlyError, AuditLogEntry
from apps.audit.services import Action, record
from tests import factories


@pytest.fixture
def world(db):
    alice, org_a = factories.user("alice")
    bob, org_b = factories.user("bob")
    repo_a = factories.repository(org_a, "alice/app")
    record(org_a, alice, Action.REPO_CONNECTED, target=repo_a, target_label="alice/app")
    record(org_a, alice, Action.REPO_REINDEXED, target=repo_a, target_label="alice/app")
    record(org_b, bob, Action.REPO_CONNECTED, target_label="bob/secret-repo")
    return locals()


# -------------------------------------------------------------- append-only


def test_an_entry_cannot_be_updated(world):
    entry = AuditLogEntry.objects.filter(organization=world["org_a"]).first()
    entry.target_label = "rewritten"

    with pytest.raises(AppendOnlyError):
        entry.save()


def test_an_entry_cannot_be_deleted(world):
    with pytest.raises(AppendOnlyError):
        AuditLogEntry.objects.first().delete()


def test_bulk_update_and_delete_are_refused(world):
    with pytest.raises(AppendOnlyError):
        AuditLogEntry.objects.all().update(action="repo.disconnected")
    with pytest.raises(AppendOnlyError):
        AuditLogEntry.objects.all().delete()
    assert AuditLogEntry.objects.count() == 3


def test_a_failed_audit_write_never_fails_the_action(world):
    with mock.patch.object(AuditLogEntry.objects, "create", side_effect=RuntimeError("db")):
        assert record(world["org_a"], world["alice"], Action.REPO_CONNECTED) is None


def test_the_actor_login_survives_the_user_being_deleted(world):
    world["alice"].delete()

    entry = AuditLogEntry.objects.filter(action="repo.connected").order_by("id").first()
    assert entry.actor is None
    assert entry.actor_login == "alice"


# --------------------------------------------------------------- endpoint


def test_the_log_shows_only_my_organisation(world):
    response = factories.client(world["alice"]).get("/api/audit-log/")

    assert response.status_code == 200
    labels = [row["target_label"] for row in response.data["results"]]
    assert labels == ["alice/app", "alice/app"]
    assert "bob/secret-repo" not in str(response.data)


def test_naming_another_organisation_in_the_header_grants_nothing(world):
    """X-Organization-Id is a preference checked against membership, never a grant."""
    response = factories.client(world["alice"], world["org_b"]).get("/api/audit-log/")

    assert "bob/secret-repo" not in str(response.data)
    assert {row["target_label"] for row in response.data["results"]} == {"alice/app"}


def test_a_member_may_not_read_the_audit_log(world):
    carol, _ = factories.user("carol")
    factories.add_member(carol, world["org_a"], Membership.Role.MEMBER)

    response = factories.client(carol, world["org_a"]).get("/api/audit-log/")

    assert response.status_code == 403


def test_an_admin_may(world):
    dana, _ = factories.user("dana")
    factories.add_member(dana, world["org_a"], Membership.Role.ADMIN)

    assert factories.client(dana, world["org_a"]).get("/api/audit-log/").status_code == 200


@pytest.mark.parametrize(
    ("query", "count"),
    [
        ("action=repo.connected", 1),
        ("action=repo.reindexed", 1),
        ("actor=alice", 2),
        ("actor=nobody", 0),
        ("q=alice", 2),
        ("q=zzz", 0),
        ("since=2000-01-01T00:00:00Z", 2),
        ("until=2000-01-01T00:00:00Z", 0),
    ],
)
def test_filters(world, query, count):
    response = factories.client(world["alice"]).get(f"/api/audit-log/?{query}")

    assert response.data["count"] == count


def test_pagination(world):
    for n in range(30):
        record(world["org_a"], world["alice"], Action.REPO_REINDEXED, target_label=f"r{n}")

    first = factories.client(world["alice"]).get("/api/audit-log/").data

    assert first["count"] == 32
    assert len(first["results"]) == 25
    assert first["next"]


# ----------------------------------------------------------- the retrofits


def test_connecting_and_disconnecting_a_repository_is_audited(world):
    from apps.repos.models import Repository

    alice, org_a = world["alice"], world["org_a"]
    remote = {"id": 777, "full_name": "alice/new", "owner": {"login": "alice"}, "name": "new"}
    api = factories.client(alice)

    with (
        mock.patch(
            "apps.repos.views.github_app.list_installation_repositories", return_value=[remote]
        ),
        mock.patch("apps.ingestion.services.start_ingestion"),
    ):
        assert api.post("/api/repos/connect/", {"github_id": 777}, format="json").status_code == 201

    connected = AuditLogEntry.objects.get(action="repo.connected", target_label="alice/new")
    assert connected.actor == alice
    assert connected.metadata == {"github_id": 777}

    repo = Repository.objects.get(github_id=777, organization=org_a)
    assert api.delete(f"/api/repos/{repo.pk}/").status_code == 204
    assert AuditLogEntry.objects.filter(
        action="repo.disconnected", target_label="alice/new"
    ).exists()


def test_a_reindex_is_audited(world):
    api = factories.client(world["alice"])
    before = AuditLogEntry.objects.filter(action="repo.reindexed").count()

    assert api.post(f"/api/repos/{world['repo_a'].pk}/reindex/").status_code == 202

    assert AuditLogEntry.objects.filter(action="repo.reindexed").count() == before + 1
