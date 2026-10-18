"""Run follow-up work off the request path.

GitHub abandons a webhook delivery after 10 seconds and does not retry, so the
handler must respond before doing anything slow (spec section 13).

This is a deliberately narrow seam, not a job queue. Celery and Redis arrive in phase
3 with the ingestion pipeline; standing up a worker process here, for one small job,
would be work phase 3 immediately redoes. `run_in_background` has the same shape as a
Celery task call, so phase 3 replaces the body and no caller changes.

`BACKGROUND_TASKS_EAGER` runs the work inline, which is how tests avoid racing a
thread. It mirrors Celery's `task_always_eager`, also named in spec section 7.
"""

import logging
import threading

from django.conf import settings
from django.db import connections

logger = logging.getLogger(__name__)


def run_in_background(func, *args, **kwargs):
    """Execute `func` without blocking the caller's response."""
    if getattr(settings, "BACKGROUND_TASKS_EAGER", False):
        # Runs on the caller's thread, so the caller still owns the database
        # connection and the transaction around it. Closing connections here would
        # pull the rug out from under whoever called us.
        _run(func, *args, **kwargs)
        return None

    thread = threading.Thread(
        target=_run_in_thread,
        args=(func, *args),
        kwargs=kwargs,
        daemon=True,
        name=getattr(func, "__name__", "background"),
    )
    thread.start()
    return thread


def _run_in_thread(func, *args, **kwargs):
    try:
        _run(func, *args, **kwargs)
    finally:
        # Django opens a connection per thread, so this one is ours to close.
        # Leaving it open leaks a Postgres backend per delivery.
        connections.close_all()


def _run(func, *args, **kwargs):
    try:
        func(*args, **kwargs)
    except Exception:
        # Never let a background failure escape: in a thread it would be lost
        # silently, and the webhook has already been answered with 202.
        logger.exception("Background task %s failed", getattr(func, "__name__", func))
