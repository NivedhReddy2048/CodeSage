"""Reviews a restart interrupted, re-queued once when the worker starts.

A deploy, a crash or Render's restart can stop the worker in the middle of a
review. The broker message was taken when the task started, so nothing redelivers
it: the Review stays pending or running for good, and the missed-webhook catch-up
counts its head SHA as reviewed and never redoes it.

So when the worker starts, a review stuck past STALE_AFTER (15 minutes, the same
age the UI calls "stalled") is put back on the queue, on its own row: an
interrupted run stores nothing (its results are written in one transaction at
the end), and reusing the row does not spend another daily free-demo slot.

At most one automatic retry per head SHA, recorded in the audit log as a re-run
with source "startup-recovery". A review interrupted again, or one whose PR has
moved on to a newer commit (which gets its own review), is marked failed with the
reason instead, and can still be re-run by hand.
"""

import logging
from collections import Counter

from django.db.models import Q
from django.utils import timezone

from apps.audit.models import AuditLogEntry
from apps.audit.services import Action
from apps.audit.services import record as audit
from apps.reviews import progress
from apps.reviews.models import STALE_AFTER, Review

logger = logging.getLogger(__name__)

SOURCE = "startup-recovery"


def stuck_reviews(now=None):
    """Pending since before the cutoff, or running and started before it."""
    cutoff = (now or timezone.now()) - STALE_AFTER
    return Review.objects.filter(
        Q(status=Review.Status.PENDING, created_at__lt=cutoff)
        | Q(status=Review.Status.RUNNING, started_at__lt=cutoff)
        | Q(status=Review.Status.RUNNING, started_at__isnull=True, created_at__lt=cutoff)
    ).select_related("pull_request__repository__installation", "pull_request__repository")


def already_retried(pull_request, head_sha):
    return AuditLogEntry.objects.filter(
        action=Action.REVIEW_RERUN,
        target_type="pullrequest",
        target_id=str(pull_request.pk),
        metadata__source=SOURCE,
        metadata__head_sha=head_sha,
    ).exists()


def recover_stuck_reviews():
    """Re-queue or close out every stuck review. Returns counts for the log."""
    summary = Counter()
    for review in stuck_reviews():
        pull_request = review.pull_request
        installation = pull_request.repository.installation
        head_sha = review.head_sha or pull_request.head_sha

        if installation is None or installation.suspended:
            _give_up(review, "the repository's GitHub App installation is gone or suspended")
        elif head_sha != pull_request.head_sha:
            _give_up(review, "the pull request has moved on to a newer commit")
        elif already_retried(pull_request, head_sha):
            _give_up(
                review,
                "it was interrupted again after its one automatic retry; re-run it by hand",
            )
        else:
            _requeue(review, installation.installation_id, head_sha)
            summary["requeued"] += 1
            continue
        summary["failed"] += 1

    logger.info("Startup review recovery: %s", dict(summary))
    return summary


def _requeue(review, installation_id, head_sha):
    from apps.reviews.tasks import review_pull_request_task

    pull_request = review.pull_request
    was = review.status
    review.status = Review.Status.PENDING
    review.started_at = None
    review.progress = {}
    review.save(update_fields=["status", "started_at", "progress"])

    audit(
        pull_request.repository.organization,
        None,
        Action.REVIEW_RERUN,
        target=pull_request,
        target_label=f"{pull_request.repository.full_name}#{pull_request.number}",
        source=SOURCE,
        review=review.pk,
        head_sha=head_sha,
        was=was,
    )
    try:
        review_pull_request_task.delay(pull_request.pk, installation_id, review.pk)
    except Exception as exc:  # noqa: BLE001 - recorded on the row, not raised at startup
        logger.exception("Could not re-queue review %s", review.pk)
        _give_up(review, f"it could not be re-queued: {exc}")


def _give_up(review, reason):
    review.status = Review.Status.FAILED
    review.error = f"Interrupted before it finished, not retried: {reason}."[:2000]
    review.finished_at = timezone.now()
    review.save(update_fields=["status", "error", "finished_at"])
    try:
        progress.announce_finished(review)
        from apps.notifications.services import notify_review

        notify_review(review)
    except Exception:  # noqa: BLE001 - the row is right; a lost notice is not worth a crash
        logger.exception("Could not announce failed review %s", review.pk)
