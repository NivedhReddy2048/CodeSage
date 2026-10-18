"""Work triggered by a webhook, running after the 202 has already gone back.

Phase 3 converts these into Celery tasks; the function signatures are chosen so that
is a change of decorator, not of logic.
"""

import logging

from django.utils import timezone

from apps.accounts.models import Membership, User
from apps.repos import github_app
from apps.repos.github_app import GitHubAppError
from apps.repos.models import AppInstallation, Repository, WebhookEvent
from apps.reviews.models import PullRequest

logger = logging.getLogger(__name__)

ACK_COMMENT_BODY = (
    "**CodeSage is reviewing this PR...**\n\n"
    "A multi-agent review is running. This comment will be updated with the findings "
    "when it completes."
)

# Actions that mean "there is code to look at". `reopened` is included because a
# PR reopened after being closed has had no review on this branch state, and the
# user's expectation is that reopening re-runs it. `edited` and `labeled` change no
# code and must not spend a review.
REVIEWABLE_ACTIONS = {"opened", "synchronize", "reopened"}


def handle_webhook_event(event_id):
    """Route a stored delivery to its handler and stamp it processed."""
    try:
        event = WebhookEvent.objects.get(pk=event_id)
    except WebhookEvent.DoesNotExist:
        logger.warning("Webhook event %s vanished before processing", event_id)
        return

    try:
        if event.event == "pull_request":
            handle_pull_request_event(event)
        elif event.event == "push":
            handle_push_event(event)
        elif event.event in {"installation", "installation_repositories"}:
            handle_installation_event(event)
        else:
            # Stored but not acted on. Keeping the row means an unexpected event type
            # is visible in the admin rather than silently dropped.
            logger.info("Ignoring %s delivery %s", event.event, event.delivery_id)
    finally:
        # Stamped even on failure: the distinction that matters is "we got to it",
        # and an exception is already logged with a traceback.
        event.processed_at = timezone.now()
        event.save(update_fields=["processed_at"])


# --------------------------------------------------------------------- installations


def upsert_installation(payload):
    """Mirror GitHub's installation record locally, creating it if new."""
    installation = payload.get("installation") or {}
    installation_id = installation.get("id")
    if not installation_id:
        return None

    account = installation.get("account") or {}
    defaults = {
        "account_login": account.get("login") or "",
        "account_type": account.get("type") or "",
        "repository_selection": installation.get("repository_selection") or "",
        "suspended": bool(installation.get("suspended_at")),
    }
    # Drop empties so a sparse payload cannot blank fields a richer one already set.
    defaults = {key: value for key, value in defaults.items() if value != ""}

    row, _ = AppInstallation.objects.update_or_create(
        installation_id=installation_id, defaults=defaults
    )
    return row


def handle_installation_event(event):
    """React to the App being installed, suspended, or removed."""
    payload = event.payload
    action = event.action
    installation = upsert_installation(payload)
    if installation is None:
        return

    if action == "deleted":
        # Detach rather than delete: the record of what was once connected is worth
        # keeping, and Repository rows survive via SET_NULL.
        installation.delete()
        logger.info("Installation %s deleted", event.installation_id)
        return

    if action in {"suspend", "unsuspend"}:
        installation.suspended = action == "suspend"
        installation.save(update_fields=["suspended", "updated_at"])


def resolve_organization(installation):
    """Decide which tenant an installation's work belongs to.

    Preference order: an explicit link made through the connect flow, then the
    personal organisation of the user whose GitHub login matches the account the App
    is installed on.

    The fallback is what lets a freshly installed App work before anyone has used the
    UI: installing the App is itself the grant of access, so a PR should get a review
    without a second confirmation step.
    """
    if installation.organization_id:
        return installation.organization

    user = User.objects.filter(github_login__iexact=installation.account_login).first()
    if user is None:
        return None

    membership = (
        Membership.objects.filter(user=user, organization__is_personal=True)
        .select_related("organization")
        .first()
    )
    if membership is None:
        return None

    # Remember it, so this lookup happens once per installation.
    installation.organization = membership.organization
    installation.save(update_fields=["organization", "updated_at"])
    return membership.organization


def ensure_repository(payload, installation):
    """Find or create the local Repository row for a webhook's repository."""
    repo = payload.get("repository") or {}
    github_id = repo.get("id")
    if not github_id or installation is None:
        return None

    organization = resolve_organization(installation)
    if organization is None:
        logger.warning(
            "No organisation for installation %s (%s); cannot attribute %s",
            installation.installation_id,
            installation.account_login,
            repo.get("full_name"),
        )
        return None

    row, _ = Repository.objects.update_or_create(
        organization=organization,
        github_id=github_id,
        defaults={
            "installation": installation,
            "full_name": repo.get("full_name") or "",
            "owner": (repo.get("owner") or {}).get("login") or "",
            "name": repo.get("name") or "",
            "default_branch": repo.get("default_branch") or "main",
            "private": bool(repo.get("private")),
        },
    )
    return row


# --------------------------------------------------------------------------- pushes


def handle_push_event(event):
    """Re-index a connected repository when its default branch moves.

    Narrow on purpose. A push webhook fires for every branch and every tag, and
    indexing is the one part of the system that spends Gemini quota, so anything
    that is not "new code on the branch we index" is ignored:

      - other branches: their code is not what retrieval answers from
      - deletions: there is nothing to index
      - repositories nobody connected: not ours to spend quota on

    The content-hash cache from phase 3 makes the remaining case cheap - an
    unchanged file costs nothing - which is what makes re-indexing on every push
    affordable at all.
    """
    payload = event.payload

    if payload.get("deleted"):
        logger.info("Ignoring branch/tag deletion for %s", event.repository_full_name)
        return

    ref = payload.get("ref") or ""
    if not ref.startswith("refs/heads/"):
        logger.info("Ignoring non-branch push %s", ref)
        return
    branch = ref[len("refs/heads/") :]

    repo_payload = payload.get("repository") or {}
    github_id = repo_payload.get("id")
    default_branch = repo_payload.get("default_branch") or ""

    if not github_id or branch != default_branch:
        logger.info("Ignoring push to %s (default is %s)", branch or "?", default_branch or "?")
        return

    # Only repositories someone deliberately connected. An installation can see
    # repositories that were never connected in the UI.
    repository = Repository.objects.filter(github_id=github_id).first()
    if repository is None:
        logger.info(
            "Ignoring push to unconnected repository %s",
            repo_payload.get("full_name"),
        )
        return

    from apps.ingestion.services import start_ingestion

    job, started = start_ingestion(repository)
    logger.info(
        "Push to %s@%s: ingestion job %s %s",
        repository.full_name,
        branch,
        job.pk,
        "queued" if started else "already running",
    )


# -------------------------------------------------------------------- pull requests


def handle_pull_request_event(event):
    """On a reviewable PR action, record it and post the acknowledgement comment."""
    if event.action not in REVIEWABLE_ACTIONS:
        logger.info("Ignoring pull_request.%s", event.action)
        return

    payload = event.payload
    installation = upsert_installation(payload)
    repository = ensure_repository(payload, installation)
    if repository is None:
        return

    pr_payload = payload.get("pull_request") or {}
    number = pr_payload.get("number")
    if not number:
        logger.warning("pull_request payload had no number (%s)", event.delivery_id)
        return

    pull_request, _ = PullRequest.objects.update_or_create(
        repository=repository,
        number=number,
        defaults={
            "github_id": pr_payload.get("id"),
            "title": pr_payload.get("title") or "",
            "author_login": (pr_payload.get("user") or {}).get("login") or "",
            "head_sha": (pr_payload.get("head") or {}).get("sha") or "",
            "base_branch": (pr_payload.get("base") or {}).get("ref") or "",
            "state": pr_payload.get("state") or "",
        },
    )

    post_acknowledgement(pull_request, installation.installation_id)

    # Hand off to the reviewer. Imported here so the repos app does not import the
    # reviews app at module load.
    from apps.reviews.tasks import review_pull_request_task

    try:
        review_pull_request_task.delay(pull_request.pk, installation.installation_id)
    except Exception:  # noqa: BLE001 - a broker outage must not lose the ack comment
        logger.exception(
            "Could not queue a review for %s#%s",
            repository.full_name,
            pull_request.number,
        )


def post_acknowledgement(pull_request, installation_id):
    """Post, or refresh, the bot's placeholder comment on a PR.

    On `synchronize` the comment already exists, so it is edited rather than
    duplicated — a PR that gets five pushes should still carry one bot comment.
    """
    repo_full_name = pull_request.repository.full_name

    try:
        if pull_request.ack_comment_id:
            github_app.update_issue_comment(
                installation_id,
                repo_full_name,
                pull_request.ack_comment_id,
                ACK_COMMENT_BODY,
            )
            return pull_request.ack_comment_id

        comment = github_app.create_issue_comment(
            installation_id, repo_full_name, pull_request.number, ACK_COMMENT_BODY
        )
    except GitHubAppError:
        logger.exception(
            "Could not post the acknowledgement comment on %s#%s",
            repo_full_name,
            pull_request.number,
        )
        return None

    comment_id = comment.get("id")
    if comment_id:
        pull_request.ack_comment_id = comment_id
        pull_request.save(update_fields=["ack_comment_id", "updated_at"])
    return comment_id
