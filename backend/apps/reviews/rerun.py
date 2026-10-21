"""Re-running a review on purpose, from the CLI or the UI.

Both paths deliberately go around the webhook's delivery-id dedupe: they create no
WebhookEvent. They share the refresh step, so a re-run always reviews the PR's
current head rather than whatever commit the last webhook named.
"""

from django.utils import timezone

from apps.audit.services import Action
from apps.audit.services import record as audit
from apps.repos import github_app
from apps.repos.github_app import GitHubAppError
from apps.reviews.models import STALE_AFTER, PullRequest, Review


class RerunRefused(Exception):
    """The re-run cannot be started; the message is safe to show the user."""


def refresh_pull_request(repository, number):
    """Read the PR's current head from GitHub and update (or create) its record."""
    installation_id = repository.installation.installation_id
    data = github_app.get_pull_request(installation_id, repository.full_name, number)
    pull_request, _ = PullRequest.objects.update_or_create(
        repository=repository,
        number=number,
        defaults={
            "github_id": data.get("id"),
            "title": data.get("title") or "",
            "author_login": (data.get("user") or {}).get("login") or "",
            "head_sha": (data.get("head") or {}).get("sha") or "",
            "base_branch": (data.get("base") or {}).get("ref") or "",
            "state": data.get("state") or "",
        },
    )
    return pull_request


def in_progress(pull_request):
    cutoff = timezone.now() - STALE_AFTER
    return Review.objects.filter(
        pull_request=pull_request,
        status__in=[Review.Status.PENDING, Review.Status.RUNNING],
        created_at__gte=cutoff,
    ).first()


def request_rerun(review, actor):
    """Queue a fresh review of `review`'s pull request. Returns the new pending Review.

    The new row exists before the worker starts, so the UI can open it and watch its
    progress socket straight away.
    """
    pull_request = review.pull_request
    repository = pull_request.repository
    if repository.installation is None:
        raise RerunRefused("This repository has no GitHub App installation.")
    if in_progress(pull_request):
        raise RerunRefused("A review of this pull request is already in progress.")

    try:
        pull_request = refresh_pull_request(repository, pull_request.number)
    except GitHubAppError as exc:
        raise RerunRefused("Could not read the pull request from GitHub.") from exc

    fresh = Review.objects.create(
        pull_request=pull_request, status=Review.Status.PENDING, head_sha=pull_request.head_sha
    )

    from apps.reviews.tasks import review_pull_request_task

    try:
        review_pull_request_task.delay(
            pull_request.pk, repository.installation.installation_id, fresh.pk
        )
    except Exception as exc:  # noqa: BLE001 - broker down: say so, leave nothing pending
        fresh.status = Review.Status.FAILED
        fresh.error = f"Could not queue the review: {exc}"[:2000]
        fresh.finished_at = timezone.now()
        fresh.save(update_fields=["status", "error", "finished_at"])
        raise RerunRefused("Could not queue the review. Is the worker's broker running?") from exc

    audit(
        repository.organization,
        actor,
        Action.REVIEW_RERUN,
        target=pull_request,
        target_label=f"{repository.full_name}#{pull_request.number}",
        previous_review=review.pk,
        new_review=fresh.pk,
        head_sha=pull_request.head_sha,
        source="api",
    )
    return fresh
