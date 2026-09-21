"""Project-level views that do not belong to any single app."""

from django.http import JsonResponse


def health(_request):
    """Liveness probe used by local smoke tests and the Render health check."""
    return JsonResponse({"status": "ok", "service": "codesage"})
