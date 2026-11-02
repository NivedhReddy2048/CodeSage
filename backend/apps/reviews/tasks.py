"""Celery tasks for the review pipeline."""

import logging

from celery import shared_task

from apps.reviews.models import PullRequest
from apps.reviews.services import review_pull_request

logger = logging.getLogger(__name__)


@shared_task(name="reviews.review_pull_request")
def review_pull_request_task(pull_request_id, installation_id, review_id=None):
    """Review a pull request off the webhook's request path.

    No retries: `review_pull_request` records its own failures on the Review and in
    the PR comment, and a provider that just exhausted a free-tier quota will not
    succeed on an immediate second attempt. Re-running is a deliberate action.
    """
    try:
        pull_request = PullRequest.objects.select_related("repository").get(pk=pull_request_id)
    except PullRequest.DoesNotExist:
        logger.warning("Pull request %s no longer exists", pull_request_id)
        return None

    from apps.reviews.models import Review

    existing = Review.objects.filter(pk=review_id).first() if review_id else None
    if existing is not None and existing.status != Review.Status.PENDING:
        # Already taken: startup recovery re-queued a review whose original message
        # was still in the queue, and whichever ran first did the work.
        logger.info("Review %s is %s, not pending; skipping", existing.pk, existing.status)
        return {"review_id": existing.pk, "status": existing.status, "skipped": True}
    review = review_pull_request(pull_request, installation_id, review=existing)
    return {"review_id": review.pk, "status": review.status}


@shared_task(name="reviews.recover_stuck")
def recover_stuck_reviews_task():
    """Re-queue reviews a restart interrupted (see apps/reviews/recovery.py)."""
    from apps.reviews.recovery import recover_stuck_reviews

    return dict(recover_stuck_reviews())
