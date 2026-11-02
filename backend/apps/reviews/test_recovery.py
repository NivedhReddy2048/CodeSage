"""Startup recovery: reviews a restart interrupted are re-queued once, then left
failed with a reason."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.audit.models import AuditLogEntry
from apps.reviews import recovery
from apps.reviews.models import Review
from apps.reviews.tasks import review_pull_request_task
from tests import factories


@pytest.fixture
def pr(db):
    _alice, org = factories.user("alice")
    return factories.pull_request(factories.repository(org, "alice/app"), number=4)


def stuck(pr, status=Review.Status.RUNNING, minutes=20, head_sha=None):
    """A review left `status` `minutes` ago, as a killed worker leaves it."""
    review = factories.review(pr, status=status)
    then = timezone.now() - timedelta(minutes=minutes)
    Review.objects.filter(pk=review.pk).update(
        created_at=then,
        started_at=then if status == Review.Status.RUNNING else None,
        head_sha=head_sha or pr.head_sha,
        progress={"security": "running"},
    )
    review.refresh_from_db()
    return review


def dispatched(broker):
    return [
        (call.args[0].name, call.kwargs.get("args") or call.args[1])
        for call in broker.call_args_list
    ]


def retries():
    return AuditLogEntry.objects.filter(action="review.rerun", metadata__source="startup-recovery")


def test_a_review_stuck_running_is_requeued_on_its_own_row(pr, never_reach_a_real_broker):
    review = stuck(pr)

    summary = recovery.recover_stuck_reviews()

    review.refresh_from_db()
    assert summary["requeued"] == 1
    assert review.status == Review.Status.PENDING
    assert review.started_at is None and review.progress == {}
    assert Review.objects.count() == 1  # no new row, so no second daily-cap slot
    installation_id = pr.repository.installation.installation_id
    assert dispatched(never_reach_a_real_broker) == [
        ("reviews.review_pull_request", (pr.pk, installation_id, review.pk))
    ]


def test_the_retry_is_in_the_audit_log_as_startup_recovery(pr):
    review = stuck(pr)

    recovery.recover_stuck_reviews()

    (entry,) = retries()
    assert entry.organization == pr.repository.organization
    assert entry.actor is None
    assert entry.target_label == "alice/app#4"
    assert entry.metadata == {
        "source": "startup-recovery",
        "review": review.pk,
        "head_sha": pr.head_sha,
        "was": "running",
    }


def test_a_review_stuck_pending_is_requeued_too(pr):
    review = stuck(pr, status=Review.Status.PENDING)

    assert recovery.recover_stuck_reviews()["requeued"] == 1
    review.refresh_from_db()
    assert review.status == Review.Status.PENDING


def test_one_automatic_retry_per_head_sha(pr, never_reach_a_real_broker):
    """Interrupted again after its retry: failed with the reason, not retried."""
    stuck(pr)
    recovery.recover_stuck_reviews()
    Review.objects.update(
        status=Review.Status.RUNNING, started_at=timezone.now() - timedelta(minutes=30)
    )
    never_reach_a_real_broker.reset_mock()

    summary = recovery.recover_stuck_reviews()

    review = Review.objects.get()
    assert summary == {"failed": 1}
    assert review.status == Review.Status.FAILED
    assert "interrupted again after its one automatic retry" in review.error
    assert review.finished_at is not None
    never_reach_a_real_broker.assert_not_called()
    assert retries().count() == 1


def test_a_new_head_sha_gets_its_own_retry(pr):
    stuck(pr)
    recovery.recover_stuck_reviews()
    Review.objects.update(status=Review.Status.FAILED)
    pr.head_sha = "f" * 40
    pr.save()
    stuck(pr)

    assert recovery.recover_stuck_reviews()["requeued"] == 1
    assert retries().count() == 2


def test_recent_reviews_are_left_alone(pr, never_reach_a_real_broker):
    """Younger than 15 minutes may simply be running or waiting their turn."""
    running = stuck(pr, minutes=10)
    pending = stuck(pr, status=Review.Status.PENDING, minutes=14)

    assert recovery.recover_stuck_reviews() == {}
    never_reach_a_real_broker.assert_not_called()
    for review in (running, pending):
        before = review.status
        review.refresh_from_db()
        assert review.status == before


def test_finished_reviews_are_never_touched(pr, never_reach_a_real_broker):
    for status in (Review.Status.DONE, Review.Status.FAILED):
        stuck(pr, status=status, minutes=120)

    assert recovery.recover_stuck_reviews() == {}
    never_reach_a_real_broker.assert_not_called()


def test_a_pr_that_moved_on_is_failed_not_retried(pr, never_reach_a_real_broker):
    review = stuck(pr, head_sha="0" * 40)  # the PR's head is now something newer

    recovery.recover_stuck_reviews()

    review.refresh_from_db()
    assert review.status == Review.Status.FAILED
    assert "moved on to a newer commit" in review.error
    never_reach_a_real_broker.assert_not_called()


def test_a_suspended_installation_is_failed_not_retried(pr):
    pr.repository.installation.suspended = True
    pr.repository.installation.save()
    review = stuck(pr)

    recovery.recover_stuck_reviews()

    review.refresh_from_db()
    assert review.status == Review.Status.FAILED
    assert "installation" in review.error


def test_a_broker_failure_leaves_the_review_failed_not_pending(pr, never_reach_a_real_broker):
    never_reach_a_real_broker.side_effect = ConnectionError("broker down")
    review = stuck(pr)

    recovery.recover_stuck_reviews()

    review.refresh_from_db()
    assert review.status == Review.Status.FAILED
    assert "could not be re-queued" in review.error


# ----------------------------------------------------------- the worker side


def test_a_duplicate_message_for_a_review_already_taken_is_ignored(pr):
    """The original message ran first; the recovery's copy must not run it again."""
    review = factories.review(pr, status=Review.Status.DONE)

    result = review_pull_request_task(pr.pk, 1, review.pk)

    assert result == {"review_id": review.pk, "status": "done", "skipped": True}


def test_a_starting_worker_queues_the_recovery(never_reach_a_real_broker):
    from core.celery import recover_on_startup

    recover_on_startup()

    names = [call.args[0].name for call in never_reach_a_real_broker.call_args_list]
    assert names == ["reviews.recover_stuck"]


def test_the_task_runs_a_pass(pr):
    stuck(pr)

    from apps.reviews.tasks import recover_stuck_reviews_task

    assert recover_stuck_reviews_task() == {"requeued": 1}
