"""Creating notifications when something a member would want to know happens."""

import logging

from apps.accounts.models import Membership
from apps.notifications.models import Notification

logger = logging.getLogger(__name__)

Kind = Notification.Kind


def notify_organization(organization, kind, title, body="", link=""):
    """One notification per member. Never raises: it must not fail the event itself."""
    if organization is None:
        return []
    try:
        members = Membership.objects.filter(organization=organization).values_list(
            "user_id", flat=True
        )
        return Notification.objects.bulk_create(
            [
                Notification(
                    organization=organization,
                    recipient_id=user_id,
                    kind=kind,
                    title=title[:255],
                    body=body[:500],
                    link=link[:255],
                )
                for user_id in members
            ]
        )
    except Exception:  # noqa: BLE001
        logger.exception("Could not create %s notifications for %s", kind, organization)
        return []


def notify_review(review):
    """Finished, degraded or failed - whichever this review ended as."""
    pull_request = review.pull_request
    repository = pull_request.repository
    where = f"{repository.full_name}#{pull_request.number}"
    link = f"/reviews/{review.pk}"

    if review.degraded:
        kind, title = Kind.REVIEW_DEGRADED, f"Review of {where} ran in degraded mode"
        body = "No AI provider answered, so the change was not reviewed."
    elif review.status == review.Status.FAILED:
        kind, title = Kind.REVIEW_FAILED, f"Review of {where} failed"
        body = "The review could not be completed."
    else:
        count = review.findings.count()
        kind, title = Kind.REVIEW_FINISHED, f"Review of {where} finished"
        body = f"{count} finding{'s' if count != 1 else ''}."
    return notify_organization(repository.organization, kind, title, body, link)


def notify_indexing_failed(job):
    repository = job.repository
    return notify_organization(
        repository.organization,
        Kind.INDEXING_FAILED,
        f"Indexing {repository.full_name} failed",
        "Code search for this repository may be stale. Re-index it from Repositories.",
        "/repos",
    )
