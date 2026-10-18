"""Celery tasks for repository indexing."""

import logging

from celery import shared_task

from apps.ingestion.indexer import index_repository
from apps.ingestion.models import IngestionJob

logger = logging.getLogger(__name__)


@shared_task(name="ingestion.index_repository")
def index_repository_task(job_id):
    """Run one IngestionJob to completion.

    Takes a job id rather than a Repository id so the row exists before the task is
    queued: the UI can show "pending" immediately, and a worker that never picks the
    task up leaves visible evidence instead of silence.

    `index_repository` records its own failures on the job, so this does not retry.
    A failed index is a thing the user re-runs from the UI once the cause is fixed,
    not something to hammer at automatically on a free tier.
    """
    try:
        job = IngestionJob.objects.select_related("repository").get(pk=job_id)
    except IngestionJob.DoesNotExist:
        logger.warning("Ingestion job %s no longer exists", job_id)
        return None

    result = index_repository(job)
    return {
        "job_id": job.pk,
        "status": job.status,
        "chunks_created": result.chunks_created,
        "chunks_reused": result.chunks_reused,
    }
