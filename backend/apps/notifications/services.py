"""Creating notifications when something a member would want to know happens."""

import logging

from apps.accounts.models import Membership
from apps.notifications.models import Notification

logger = logging.getLogger(__name__)

Kind = Notification.Kind


def notify_organization(organization, kind, title, body="", link="", meta=None):
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
                    meta=meta or {},
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
    # Short first, so a narrow menu truncates the outcome rather than the PR number;
    # the full owner/name goes in `meta` for a tooltip.
    where = f"{repository.name or repository.full_name} #{pull_request.number}"
    link = f"/reviews/{review.pk}"
    meta = {
        "repository": repository.full_name,
        "pr_number": pull_request.number,
        "head_sha": review.head_sha,
        "trigger": review.trigger,
    }

    if review.degraded:
        kind, title = Kind.REVIEW_DEGRADED, f"{where} · degraded"
        body = "No AI provider answered, so the change was not reviewed."
    elif review.status == review.Status.FAILED:
        kind, title = Kind.REVIEW_FAILED, f"{where} · failed"
        body = "The review could not be completed."
    else:
        kind, title = Kind.REVIEW_FINISHED, f"{where} · {finding_summary(review)}"
        body = "Review finished."
    return notify_organization(repository.organization, kind, title, body, link, meta)


def finding_summary(review):
    """ "2 blocking · 1 nit", "1 nit", or "no issues"."""
    blocking = review.findings.filter(severity="blocking").count()
    nits = review.findings.exclude(severity="blocking").count()
    parts = []
    if blocking:
        parts.append(f"{blocking} blocking")
    if nits:
        parts.append(f"{nits} nit{'s' if nits != 1 else ''}")
    return " · ".join(parts) or "no issues"


def notify_indexing_failed(job):
    repository = job.repository
    return notify_organization(
        repository.organization,
        Kind.INDEXING_FAILED,
        f"Indexing {repository.full_name} failed",
        "Code search for this repository may be stale. Re-index it from Repositories.",
        "/repos",
    )
