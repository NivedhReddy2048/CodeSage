"""Reviews for pull requests whose webhook never arrived.

The free web service sleeps outside the keep-warm window (docs/DEPLOY.md), and
GitHub gives a webhook delivery 10 seconds and never retries it. A PR opened or
pushed while CodeSage slept is otherwise never reviewed.

So on worker startup, and at most every CATCHUP_INTERVAL_SECONDS while awake
(triggered by the keep-warm ping hitting /api/health/, so no beat process), each
connected repository's open PRs are compared with what has been reviewed, and any
head SHA with no review is reviewed through the webhook path itself. A default
branch whose head moved since the last index is re-indexed.

NEON. Postgres scales to zero and bills compute-hours, so a run asks GitHub first
and Redis second; the database only hears about a head SHA Redis does not already
know was reviewed. The connected-repository list, the reviewed SHAs and the last
indexed head all live in the cache with TTLs, so a run where nothing changed makes
no database query at all (tested).
"""

import logging
from collections import Counter

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.repos import github_app
from apps.repos.github_app import GitHubAppError

logger = logging.getLogger(__name__)

DUE_KEY = "catchup:due"
REPOSITORIES_KEY = "catchup:repositories"
REPOSITORIES_TTL = 6 * 60 * 60
# A reviewed SHA stays reviewed; the TTL only bounds what the cache holds.
REVIEWED_TTL = 14 * 24 * 60 * 60
INDEXED_TTL = 24 * 60 * 60

# The pull_request action the catch-up files its synthetic deliveries under, so the
# webhook handler can tell them apart (the review is recorded as a catch-up).
CATCHUP_ACTION = "catchup"


def _reviewed_key(repository_id, sha):
    return f"catchup:reviewed:{repository_id}:{sha}"


def _indexed_key(repository_id):
    return f"catchup:indexed:{repository_id}"


# ---------------------------------------------------------------- scheduling


def schedule(force=False):
    """Queue a catch-up run unless one was queued within the interval. Never raises.

    Touches Redis and the broker only, never the database: the health endpoint calls
    this on every keep-warm ping. `force` is for worker startup, when sleep may have
    swallowed webhooks no matter how recently the last run was.
    """
    try:
        interval = settings.CATCHUP_INTERVAL_SECONDS
        stamp = timezone.now().isoformat()
        if force:
            cache.set(DUE_KEY, stamp, timeout=interval)
        elif not cache.add(DUE_KEY, stamp, timeout=interval):
            return False

        from apps.repos.tasks import catch_up_task

        catch_up_task.delay()
        return True
    except Exception:  # noqa: BLE001 - a broken catch-up must not fail a health check
        logger.exception("Could not schedule the webhook catch-up")
        return False


# ------------------------------------------------------------------- caching


def connected_repositories():
    """Connected repositories reachable through a live installation, cached.

    Plain dicts, so the cached value carries no model instances across processes.
    Invalidated whenever a repository or installation row changes (apps.py).
    """
    rows = cache.get(REPOSITORIES_KEY)
    if rows is None:
        from apps.repos.models import Repository

        rows = list(
            Repository.objects.filter(
                installation__isnull=False, installation__suspended=False
            ).values(
                "id",
                "github_id",
                "full_name",
                "default_branch",
                "installation__installation_id",
            )
        )
        cache.set(REPOSITORIES_KEY, rows, timeout=REPOSITORIES_TTL)
    return rows


def forget_repositories(**_kwargs):
    """Drop the cached repository list (a signal receiver, hence the kwargs)."""
    cache.delete(REPOSITORIES_KEY)


def repository_saved(instance, created, **_kwargs):
    """A new connection changes the list; the webhook's routine re-save does not.

    Every pull_request delivery re-saves its repository (update_or_create), and
    dropping the list each time would cost a query per run for nothing.
    """
    if created:
        forget_repositories()


def installation_saved(instance, **_kwargs):
    """Drop the list only when this installation's place in it is now wrong.

    Listed but suspended, or live but missing (new, or just unsuspended). Every
    delivery re-saves its installation too, and that alone changes nothing.
    """
    rows = cache.get(REPOSITORIES_KEY)
    if rows is None:
        return
    listed = any(row["installation__installation_id"] == instance.installation_id for row in rows)
    if listed == instance.suspended:
        forget_repositories()


def mark_reviewed(repository_id, sha):
    """Remember that `sha` has a review, so the next catch-up need not ask Postgres."""
    if not sha:
        return
    try:
        cache.set(_reviewed_key(repository_id, sha), 1, timeout=REVIEWED_TTL)
    except Exception:  # noqa: BLE001 - the database still knows; this only saves a query
        logger.warning("Could not cache reviewed SHA %s", sha, exc_info=True)


# ----------------------------------------------------------------------- run


def catch_up():
    """One pass over every connected repository. Returns counts for the log."""
    summary = Counter()
    floor = settings.CATCHUP_RATE_LIMIT_FLOOR
    by_installation = {}
    for repo in connected_repositories():
        by_installation.setdefault(repo["installation__installation_id"], []).append(repo)

    for installation_id, repositories in by_installation.items():
        for repo in repositories:
            try:
                pulls, remaining = github_app.list_open_pull_requests(
                    installation_id, repo["full_name"]
                )
                head, after_branch = github_app.get_branch_head(
                    installation_id, repo["full_name"], repo["default_branch"]
                )
            except GitHubAppError as exc:
                # A 403/429 from a spent rate limit lands here too. Either way the
                # rest of this installation would fail the same way; other
                # installations have their own budgets.
                logger.warning("Catch-up skipped %s: %s", repo["full_name"], exc)
                summary["errors"] += 1
                break
            summary["repositories"] += 1
            remaining = after_branch if after_branch is not None else remaining

            _catch_up_reviews(repo, installation_id, pulls, summary)
            _catch_up_index(repo, head, summary)

            if remaining is not None and remaining < floor:
                logger.warning(
                    "Catch-up paused installation %s: %s GitHub requests left this hour",
                    installation_id,
                    remaining,
                )
                summary["rate_limited"] += 1
                break

    logger.info("Webhook catch-up: %s", dict(summary))
    return summary


def _catch_up_reviews(repo, installation_id, pulls, summary):
    heads = {}
    for pull in pulls:
        sha = (pull.get("head") or {}).get("sha")
        if sha and pull.get("number"):
            heads[sha] = pull
    if not heads:
        return

    known = cache.get_many([_reviewed_key(repo["id"], sha) for sha in heads])
    unknown = [sha for sha in heads if _reviewed_key(repo["id"], sha) not in known]
    summary["cached"] += len(heads) - len(unknown)
    if not unknown:
        return

    from apps.reviews.models import Review

    reviewed = set(
        Review.objects.filter(
            pull_request__repository_id=repo["id"], head_sha__in=unknown
        ).values_list("head_sha", flat=True)
    )
    for sha in unknown:
        if sha in reviewed:
            mark_reviewed(repo["id"], sha)
            summary["already_reviewed"] += 1
        elif _deliver(repo, installation_id, heads[sha]):
            summary["queued"] += 1


def _deliver(repo, installation_id, pull):
    """File the missed delivery and run it through the webhook handler.

    Idempotent the way webhooks are: the delivery id is unique, so a second run (or
    a second worker) racing on the same PR head loses at get_or_create. The UTC day
    is part of the id, so a PR deferred today (the daily cap, phase 7d) is tried
    again tomorrow rather than never.
    """
    from apps.repos.models import WebhookEvent
    from apps.repos.tasks import handle_webhook_event

    sha = pull["head"]["sha"]
    day = timezone.now().date().isoformat()
    delivery_id = f"catchup:{day}:{repo['github_id']}:{pull['number']}:{sha}"
    event, created = WebhookEvent.objects.get_or_create(
        delivery_id=delivery_id,
        defaults={
            "event": "pull_request",
            "action": CATCHUP_ACTION,
            "installation_id": installation_id,
            "repository_full_name": repo["full_name"],
            "payload": _payload(repo, installation_id, pull),
        },
    )
    if not created:
        return False
    handle_webhook_event(event.pk)
    return True


def _payload(repo, installation_id, pull):
    """A pull_request delivery's shape, with only the fields the handler reads."""
    base_repo = (pull.get("base") or {}).get("repo") or {}
    owner, _, name = repo["full_name"].partition("/")
    return {
        "action": CATCHUP_ACTION,
        "installation": {"id": installation_id},
        "repository": {
            "id": repo["github_id"],
            "full_name": repo["full_name"],
            "name": base_repo.get("name") or name,
            "owner": {"login": (base_repo.get("owner") or {}).get("login") or owner},
            "default_branch": base_repo.get("default_branch") or repo["default_branch"],
            "private": bool(base_repo.get("private")),
        },
        "pull_request": {
            "number": pull["number"],
            "id": pull.get("id"),
            "title": pull.get("title") or "",
            "user": {"login": (pull.get("user") or {}).get("login") or ""},
            "head": {"sha": pull["head"]["sha"]},
            "base": {"ref": (pull.get("base") or {}).get("ref") or ""},
            "state": pull.get("state") or "open",
        },
    }


def _catch_up_index(repo, head, summary):
    """Re-index when the default branch moved past the last indexed commit.

    Only a repository that was indexed successfully before: one whose indexing keeps
    failing is not retried every half hour on Gemini's quota. And a head is
    attempted once a day at most, whatever the outcome.
    """
    if not head:
        return
    key = _indexed_key(repo["id"])
    if cache.get(key) == head:
        return

    from apps.ingestion.services import last_indexed_job, start_ingestion
    from apps.repos.models import Repository

    repository = Repository.objects.filter(pk=repo["id"]).first()
    job = last_indexed_job(repository) if repository else None
    if job is not None and job.commit_sha != head:
        _job, started = start_ingestion(repository)
        summary["reindexed" if started else "index_busy"] += 1
    cache.set(key, head, timeout=INDEXED_TTL)
