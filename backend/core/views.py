"""Project-level views that do not belong to any single app."""

from django.http import JsonResponse


def health(_request):
    """Liveness probe, and the keep-warm ping's target.

    Never touches the database: the ping arrives every few minutes all day, and a
    query would keep Neon's scale-to-zero compute awake (tests/test_production_
    settings.py fails if one appears). It does nudge the missed-webhook catch-up,
    which is throttled in Redis to one run per interval and queued, not run here.
    """
    from apps.repos import catchup

    catchup.schedule()
    return JsonResponse({"status": "ok", "service": "codesage"})
