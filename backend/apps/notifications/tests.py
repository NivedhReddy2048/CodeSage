"""Notifications: fanned out per member, private to their recipient and organisation."""

import pytest

from apps.accounts.models import Membership
from apps.ingestion.models import IngestionJob
from apps.notifications.models import Notification
from apps.notifications.services import notify_indexing_failed, notify_review
from apps.reviews.models import Review
from tests import factories


@pytest.fixture
def world(db):
    alice, org_a = factories.user("alice")
    carol, _ = factories.user("carol")
    factories.add_member(carol, org_a, Membership.Role.MEMBER)
    bob, org_b = factories.user("bob")
    pr_a = factories.pull_request(factories.repository(org_a, "alice/app"), 4)
    pr_b = factories.pull_request(factories.repository(org_b, "bob/app"), 9)
    return locals()


def test_a_finished_review_notifies_every_member(world):
    review = factories.review(world["pr_a"], findings=[("nit", "style", "security")])

    notify_review(review)

    notes = Notification.objects.filter(kind="review.finished")
    assert {n.recipient for n in notes} == {world["alice"], world["carol"]}
    assert all(n.organization == world["org_a"] for n in notes)
    note = notes.first()
    assert note.title == "Review of alice/app#4 finished"
    assert note.body == "1 finding."
    assert note.link == f"/reviews/{review.pk}"


@pytest.mark.parametrize(
    ("status", "degraded", "kind"),
    [
        (Review.Status.FAILED, True, "review.degraded"),
        (Review.Status.FAILED, False, "review.failed"),
    ],
)
def test_degraded_and_failed_reviews_have_their_own_kinds(world, status, degraded, kind):
    notify_review(factories.review(world["pr_a"], status, degraded=degraded))

    assert set(Notification.objects.values_list("kind", flat=True)) == {kind}


def test_a_failed_indexing_job_notifies_the_organisation(world):
    job = IngestionJob.objects.create(
        repository=world["pr_a"].repository, status=IngestionJob.Status.FAILED
    )

    notify_indexing_failed(job)

    assert Notification.objects.filter(kind="indexing.failed").count() == 2


def test_the_indexing_task_notifies_on_failure(world):
    from unittest import mock

    from apps.ingestion.tasks import index_repository_task

    job = IngestionJob.objects.create(repository=world["pr_a"].repository)

    def fail(job):
        job.status = IngestionJob.Status.FAILED
        job.save()
        return mock.Mock(chunks_created=0, chunks_reused=0)

    with mock.patch("apps.ingestion.tasks.index_repository", side_effect=fail):
        index_repository_task(job.pk)

    assert Notification.objects.filter(kind="indexing.failed").exists()


def test_the_list_holds_only_my_notifications_with_an_unread_count(world):
    notify_review(factories.review(world["pr_a"]))
    notify_review(factories.review(world["pr_b"]))

    data = factories.client(world["alice"]).get("/api/notifications/").data

    assert data["unread_count"] == 1
    assert len(data["results"]) == 1
    assert data["results"][0]["title"].startswith("Review of alice/app#4")


def test_marking_read(world):
    notify_review(factories.review(world["pr_a"]))
    mine = Notification.objects.get(recipient=world["alice"])
    api = factories.client(world["alice"])

    response = api.post(f"/api/notifications/{mine.pk}/read/")

    assert response.status_code == 200
    assert response.data["read"] is True
    assert api.get("/api/notifications/").data["unread_count"] == 0
    # Read state is per person: Carol's copy is untouched.
    assert Notification.objects.get(recipient=world["carol"]).read_at is None


def test_another_users_notification_cannot_be_marked_read(world):
    notify_review(factories.review(world["pr_a"]))
    carols = Notification.objects.get(recipient=world["carol"])

    response = factories.client(world["alice"]).post(f"/api/notifications/{carols.pk}/read/")

    assert response.status_code == 404
    carols.refresh_from_db()
    assert carols.read_at is None


def test_another_organisations_notification_cannot_be_marked_read(world):
    notify_review(factories.review(world["pr_b"]))
    bobs = Notification.objects.get(recipient=world["bob"])

    response = factories.client(world["alice"]).post(f"/api/notifications/{bobs.pk}/read/")

    assert response.status_code == 404


def test_read_all_touches_only_mine(world):
    notify_review(factories.review(world["pr_a"]))
    notify_review(factories.review(world["pr_a"]))

    response = factories.client(world["alice"]).post("/api/notifications/read-all/")

    assert response.data == {"marked": 2}
    assert Notification.objects.filter(recipient=world["carol"], read_at__isnull=True).count() == 2


def test_notifications_follow_the_selected_organisation(world):
    """Carol belongs to two organisations; the switcher decides which bell she sees."""
    notify_review(factories.review(world["pr_a"]))
    carols_own = factories.repository(
        world["carol"].memberships.get(role="owner").organization, "carol/app"
    )
    notify_review(factories.review(factories.pull_request(carols_own)))
    org_a = world["org_a"]

    in_a = factories.client(world["carol"], org_a).get("/api/notifications/").data
    personal = factories.client(world["carol"]).get("/api/notifications/").data

    assert [n["title"] for n in in_a["results"]] == ["Review of alice/app#4 finished"]
    assert [n["title"] for n in personal["results"]] == ["Review of carol/app#1 finished"]


def test_notifications_require_authentication(db):
    from rest_framework.test import APIClient

    assert APIClient().get("/api/notifications/").status_code == 401
