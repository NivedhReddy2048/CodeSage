"""Starting and inspecting ingestion jobs."""

import logging

from apps.ingestion.models import IngestionJob

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = (IngestionJob.Status.PENDING, IngestionJob.Status.RUNNING)


def active_job(repository):
    """The job currently queued or running for this repository, if any."""
    return (
        IngestionJob.objects.filter(repository=repository, status__in=ACTIVE_STATUSES)
        .order_by("-created_at")
        .first()
    )


def latest_job(repository):
    return IngestionJob.objects.filter(repository=repository).order_by("-created_at").first()


def last_indexed_job(repository):
    """The most recent job that finished: what the index holds right now.

    Not the latest job: while a re-index runs, the stored chunks are still the
    previous run's, and the latest job has no commit until it finishes.
    """
    return (
        IngestionJob.objects.filter(repository=repository, status=IngestionJob.Status.DONE)
        .exclude(commit_sha="")
        .order_by("-created_at")
        .first()
    )


def start_ingestion(repository, force=False):
    """Queue an indexing job, returning `(job, started)`.

    Refuses to queue a second job while one is already pending or running. Two
    concurrent runs over the same repository would race on the delete-then-insert in
    the indexer and could leave the chunk set half-written; `force` exists only for
    the case where a worker died and left a job stuck.
    """
    existing = active_job(repository)
    if existing and not force:
        return existing, False

    job = IngestionJob.objects.create(repository=repository, status=IngestionJob.Status.PENDING)

    # Imported here rather than at module scope: core.celery imports Django settings,
    # and importing it from a module the app registry loads early risks a cycle.
    from apps.ingestion.tasks import index_repository_task

    try:
        index_repository_task.delay(job.pk)
    except Exception as exc:  # noqa: BLE001 - broker down must not 500 the request
        job.status = IngestionJob.Status.FAILED
        job.error = f"Could not queue the indexing task: {exc}"
        job.save(update_fields=["status", "error"])
        logger.exception("Could not queue ingestion for %s", repository.full_name)
        return job, False

    return job, True
