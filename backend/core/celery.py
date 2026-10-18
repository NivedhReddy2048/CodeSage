"""Celery application.

On Render's free tier there is no Background Worker service type, so the worker runs
co-located with Daphne in the same container under one start command (spec section 7).
That makes the broker a local-ish hop and keeps everything inside the 750 free
instance-hours; the tradeoff, and the fact production would split them, is documented
in the README.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

app = Celery("codesage")

# Every CELERY_* setting in Django settings becomes Celery config, so there is one
# place to look rather than two.
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
