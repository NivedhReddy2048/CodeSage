import json
import logging

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.repos import webhooks
from apps.repos.dispatch import run_in_background
from apps.repos.models import WebhookEvent
from apps.repos.tasks import handle_webhook_event

logger = logging.getLogger(__name__)


class GitHubWebhookView(APIView):
    """Receive GitHub App webhook deliveries.

    The one endpoint in the project with a hard latency budget: GitHub abandons a
    delivery after 10 seconds and does not retry automatically, so a timeout has to be
    redelivered by hand. This handler therefore only verifies, stores, enqueues and
    returns 202 — every GitHub API call happens after the response (spec section 13).
    """

    # Public by necessity: GitHub cannot present a JWT. The HMAC signature is the
    # authentication, which is why an unsigned request is a 401 rather than a 403.
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        request=None,
        responses={
            202: OpenApiResponse(description="Delivery accepted and queued."),
            400: OpenApiResponse(description="Malformed delivery."),
            401: OpenApiResponse(description="Missing or invalid signature."),
        },
        description=(
            "GitHub App webhook receiver. Verifies X-Hub-Signature-256, stores the "
            "delivery, queues the follow-up work and returns 202 without blocking."
        ),
    )
    def post(self, request):
        # Raw bytes, read before any parsing: the HMAC covers exactly what GitHub
        # sent, and re-serialising parsed JSON would produce different bytes.
        raw_body = request.body

        try:
            webhooks.verify_signature(raw_body, request.headers.get(webhooks.SIGNATURE_HEADER, ""))
        except webhooks.WebhookSignatureError as exc:
            logger.warning("Rejected webhook delivery: %s", exc)
            return Response({"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED)

        delivery_id = request.headers.get("X-GitHub-Delivery", "")
        event_name = request.headers.get("X-GitHub-Event", "")
        if not delivery_id or not event_name:
            return Response(
                {"detail": "Missing X-GitHub-Delivery or X-GitHub-Event header."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = json.loads(raw_body)
        except ValueError:
            return Response(
                {"detail": "Body is not valid JSON."}, status=status.HTTP_400_BAD_REQUEST
            )
        if not isinstance(payload, dict):
            return Response(
                {"detail": "Body is not a JSON object."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        repository = payload.get("repository") or {}
        installation = payload.get("installation") or {}

        # get_or_create on the unique delivery_id is the idempotency guard: GitHub
        # reuses the id on a manual redelivery, so a replay loses the race here
        # instead of queueing a second review.
        event, created = WebhookEvent.objects.get_or_create(
            delivery_id=delivery_id,
            defaults={
                "event": event_name,
                "action": payload.get("action") or "",
                "installation_id": installation.get("id"),
                "repository_full_name": repository.get("full_name") or "",
                "payload": payload,
            },
        )

        if not created:
            logger.info("Ignoring duplicate delivery %s", delivery_id)
            return Response(
                {"detail": "Duplicate delivery ignored.", "delivery_id": delivery_id},
                status=status.HTTP_202_ACCEPTED,
            )

        run_in_background(handle_webhook_event, event.pk)

        return Response(
            {"detail": "Accepted.", "delivery_id": delivery_id, "event": event_name},
            status=status.HTTP_202_ACCEPTED,
        )
