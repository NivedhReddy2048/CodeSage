"""Celery application.

On Render's free tier there is no Background Worker service type, so the worker runs
co-located with Daphne in the same container under one start command (spec section 7).
That makes the broker a local-ish hop and keeps everything inside the 750 free
instance-hours; the tradeoff, and the fact production would split them, is documented
in the README.
"""

import os

from celery import Celery
from celery.signals import worker_ready

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

app = Celery("codesage")

# Every CELERY_* setting in Django settings becomes Celery config, so there is one
# place to look rather than two.
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@worker_ready.connect
def catch_up_on_startup(**_kwargs):
    """A worker that just started may have slept through webhooks: catch up now."""
    from apps.repos import catchup

    catchup.schedule(force=True)


@worker_ready.connect
def recover_on_startup(**_kwargs):
    """A worker that just started may have been killed mid-review: re-queue those.

    Startup only, by design: while a worker runs, a long review is not a stuck one.
    Queued rather than run here, so it runs after whatever was already waiting.
    """
    try:
        from apps.reviews.tasks import recover_stuck_reviews_task

        recover_stuck_reviews_task.delay()
    except Exception:  # noqa: BLE001 - recovery failing must not stop the worker starting
        import logging

        logging.getLogger(__name__).exception("Could not queue startup review recovery")
