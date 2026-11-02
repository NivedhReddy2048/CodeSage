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


def test_date_only_bounds_cover_the_whole_day(world):
    """A browser date input sends YYYY-MM-DD; it must filter, not be ignored."""
    from django.utils import timezone

    today = timezone.localdate().isoformat()
    api = factories.client(world["alice"])

    assert api.get(f"/api/audit-log/?since={today}&until={today}").data["count"] == 2
    assert api.get("/api/audit-log/?until=2000-01-01").data["count"] == 0
    assert api.get("/api/audit-log/?since=2999-01-01").data["count"] == 0
    # Garbage is ignored rather than erroring.
    assert api.get("/api/audit-log/?since=yesterday").data["count"] == 2


# -------------------------------------------------------------- client address


def _request(forwarded=None, remote="10.0.0.1"):
    from django.test import RequestFactory

    extra = {"REMOTE_ADDR": remote}
    if forwarded is not None:
        extra["HTTP_X_FORWARDED_FOR"] = forwarded
    return RequestFactory().get("/", **extra)


@pytest.mark.parametrize(
    ("hops", "forwarded", "expected"),
    [
        # Local: no proxy, so the header is the client's own claim and is ignored.
        (0, "203.0.113.7", "10.0.0.1"),
        # Render: the proxy appended the address it saw - the rightmost entry.
        (1, "203.0.113.7", "203.0.113.7"),
        # A client that sends its own header cannot choose what gets recorded.
        (1, "198.51.100.66, 203.0.113.7", "203.0.113.7"),
        (1, " 198.51.100.66 ,203.0.113.7 ", "203.0.113.7"),
        # Two proxies (e.g. a CDN in front of Render): one further left.
        (2, "198.51.100.66, 203.0.113.7, 172.16.0.9", "203.0.113.7"),
        # A chain shorter than the proxies we expect: fall back to the socket peer.
        (1, "", "10.0.0.1"),
        (2, "203.0.113.7", "10.0.0.1"),
    ],
)
def test_the_client_ip_is_counted_from_the_right(settings, hops, forwarded, expected):
    from apps.audit.services import client_ip

    settings.TRUSTED_PROXY_HOPS = hops

    assert client_ip(_request(forwarded)) == expected


def test_no_request_means_no_ip():
    from apps.audit.services import client_ip

    assert client_ip(None) == ""


# ----------------------------------------------- hop-count misconfiguration

# What production saw: the client, then Cloudflare's edge, then Render's proxy. The
# client is a public address: documentation ranges (203.0.113.0/24) are not global.
RENDER_CHAIN = "93.184.216.34, 172.71.10.20, 10.196.4.5"


@pytest.mark.parametrize(
    ("hops", "recorded", "warning"),
    [
        (1, "10.196.4.5", "private or internal address"),  # Render's proxy
        (2, "172.71.10.20", "Cloudflare edge address"),  # Cloudflare
        (3, "93.184.216.34", ""),  # the client: what production needs
    ],
)
def test_a_hop_count_that_stops_at_a_proxy_is_flagged(settings, hops, recorded, warning):
    from apps.audit.services import client_ip, client_ip_warning

    settings.TRUSTED_PROXY_HOPS = hops
    request = _request(RENDER_CHAIN)

    ip = client_ip(request)

    assert ip == recorded
    if warning:
        assert warning in client_ip_warning(request, ip)
        assert f"TRUSTED_PROXY_HOPS ({hops})" in client_ip_warning(request, ip)
    else:
        assert client_ip_warning(request, ip) == ""


def test_a_cloudflare_ipv6_edge_address_is_flagged(settings):
    from apps.audit.services import client_ip_warning

    settings.TRUSTED_PROXY_HOPS = 1

    edge = "2606:4700:10::ac43:1"

    assert "Cloudflare" in client_ip_warning(_request(edge), edge)


def test_a_header_shorter_than_the_hop_count_is_flagged(settings):
    from apps.audit.services import client_ip, client_ip_warning

    settings.TRUSTED_PROXY_HOPS = 3
    request = _request("93.184.216.34")

    assert "X-Forwarded-For has 1 entries but TRUSTED_PROXY_HOPS is 3" in client_ip_warning(
        request, client_ip(request)
    )


def test_local_development_is_never_flagged(settings):
    """No proxy: 127.0.0.1 is the honest answer, not a misconfiguration."""
    from apps.audit.services import client_ip, client_ip_warning

    settings.TRUSTED_PROXY_HOPS = 0
    request = _request(None, remote="127.0.0.1")

    assert client_ip_warning(request, client_ip(request)) == ""


@pytest.mark.django_db
def test_a_flagged_address_is_in_the_entry_and_the_log(settings, caplog):
    from apps.audit.services import record_auth

    settings.TRUSTED_PROXY_HOPS = 1
    alice, _org = factories.user("alice")

    with caplog.at_level("WARNING", logger="apps.audit.services"):
        (entry,) = record_auth(alice, Action.AUTH_SIGNED_IN, _request(RENDER_CHAIN))

    assert entry.metadata["ip"] == "10.196.4.5"
    assert "TRUSTED_PROXY_HOPS (1) is probably too low" in entry.metadata["ip_warning"]
    assert "Client IP looks wrong" in caplog.text


@pytest.mark.django_db
def test_a_correct_address_adds_no_warning(settings):
    from apps.audit.services import record_auth

    settings.TRUSTED_PROXY_HOPS = 3
    alice, _org = factories.user("alice")

    (entry,) = record_auth(alice, Action.AUTH_SIGNED_IN, _request(RENDER_CHAIN))

    assert entry.metadata["ip"] == "93.184.216.34"
    assert "ip_warning" not in entry.metadata
