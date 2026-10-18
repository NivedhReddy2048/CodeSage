import json
import logging

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.repos import github_app, services, webhooks
from apps.repos.dispatch import run_in_background
from apps.repos.github_app import GitHubAppError
from apps.repos.models import Repository, WebhookEvent
from apps.repos.serializers import (
    InstallableResponseSerializer,
    RepositoryConnectSerializer,
    RepositorySerializer,
)
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


class OrganizationScopedMixin:
    """Resolves the caller's organisation once, for every repository endpoint."""

    permission_classes = [IsAuthenticated]

    @property
    def organization(self):
        return services.current_organization(self.request.user)


class RepositoryListView(OrganizationScopedMixin, ListAPIView):
    """Repositories connected to the caller's organisation."""

    serializer_class = RepositorySerializer
    pagination_class = None

    def get_queryset(self):
        organization = self.organization
        if organization is None:
            return Repository.objects.none()
        # Filtered by organisation, never by id alone: this is the tenancy boundary.
        return Repository.objects.filter(organization=organization).select_related(
            "installation", "connected_by"
        )


class InstallableRepositoryListView(OrganizationScopedMixin, APIView):
    """What the GitHub App installation can reach, and what is already connected."""

    @extend_schema(
        responses={200: InstallableResponseSerializer},
        description=(
            "Repositories visible to the caller's GitHub App installation, each "
            "flagged as connected or not. When the App is not installed, returns "
            "installed=false and the URL to install it."
        ),
    )
    def get(self, request):
        organization = self.organization
        installations = list(services.installations_for(request.user, organization))

        try:
            url = github_app.install_url()
        except GitHubAppError:
            # A missing or broken App credential should not break the page; the user
            # still needs to see their connected repositories.
            logger.exception("Could not resolve the GitHub App install URL")
            url = ""

        if not installations:
            return Response({"installed": False, "install_url": url, "repositories": []})

        connected_ids = set(
            Repository.objects.filter(organization=organization).values_list("github_id", flat=True)
        )

        repositories = []
        seen = set()
        for installation in installations:
            try:
                remote = github_app.list_installation_repositories(installation.installation_id)
            except GitHubAppError as exc:
                logger.warning(
                    "Could not list repositories for installation %s: %s",
                    installation.installation_id,
                    exc,
                )
                continue

            for repo in remote:
                github_id = repo.get("id")
                # Two installations can expose the same repo; show it once.
                if not github_id or github_id in seen:
                    continue
                seen.add(github_id)
                repositories.append(
                    {
                        "github_id": github_id,
                        "full_name": repo.get("full_name") or "",
                        "owner": (repo.get("owner") or {}).get("login") or "",
                        "name": repo.get("name") or "",
                        "default_branch": repo.get("default_branch") or "main",
                        "private": bool(repo.get("private")),
                        "connected": github_id in connected_ids,
                    }
                )

        repositories.sort(key=lambda item: item["full_name"].lower())
        return Response({"installed": True, "install_url": url, "repositories": repositories})


class RepositoryConnectView(OrganizationScopedMixin, APIView):
    """Connect one repository to the caller's organisation."""

    @extend_schema(
        request=RepositoryConnectSerializer,
        responses={
            201: RepositorySerializer,
            200: RepositorySerializer,
            400: OpenApiResponse(description="No organisation, or repository not reachable."),
            403: OpenApiResponse(description="Requires the owner or admin role."),
        },
        description=(
            "Connects a repository the App installation can reach. Idempotent: "
            "connecting an already-connected repository returns it with 200."
        ),
    )
    def post(self, request):
        serializer = RepositoryConnectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        github_id = serializer.validated_data["github_id"]

        organization = self.organization
        if organization is None:
            return Response(
                {"detail": "You do not belong to an organisation."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            services.require_management_role(request.user, organization)
        except services.PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        # Resolved against GitHub rather than trusting the posted id: this is what
        # stops a caller connecting a repository the App cannot actually reach.
        match, installation = self._find_remote(request.user, organization, github_id)
        if match is None:
            return Response(
                {"detail": ("That repository is not available to your GitHub App installation.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        repository, created = Repository.objects.update_or_create(
            organization=organization,
            github_id=github_id,
            defaults={
                "installation": installation,
                "full_name": match.get("full_name") or "",
                "owner": (match.get("owner") or {}).get("login") or "",
                "name": match.get("name") or "",
                "default_branch": match.get("default_branch") or "main",
                "private": bool(match.get("private")),
                "connected_by": request.user,
            },
        )

        # Pin the installation to this organisation. From here the webhook path uses
        # this link instead of falling back to GitHub-login matching.
        if installation.organization_id != organization.id:
            installation.organization = organization
            installation.save(update_fields=["organization", "updated_at"])

        return Response(
            RepositorySerializer(repository).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def _find_remote(self, user, organization, github_id):
        for installation in services.installations_for(user, organization):
            try:
                remote = github_app.list_installation_repositories(installation.installation_id)
            except GitHubAppError as exc:
                logger.warning("Could not list installation repositories: %s", exc)
                continue
            for repo in remote:
                if repo.get("id") == github_id:
                    return repo, installation
        return None, None


class RepositoryDetailView(OrganizationScopedMixin, APIView):
    """Disconnect a repository."""

    @extend_schema(
        responses={
            204: OpenApiResponse(description="Disconnected."),
            403: OpenApiResponse(description="Requires the owner or admin role."),
            404: OpenApiResponse(description="Not connected to your organisation."),
        },
        description=(
            "Disconnects a repository from the caller's organisation. The GitHub App "
            "installation itself is unaffected; uninstall it on GitHub to revoke access."
        ),
    )
    def delete(self, request, pk):
        organization = self.organization
        try:
            services.require_management_role(request.user, organization)
        except services.PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        # Scoped lookup: another tenant's repository must read as absent, not forbidden.
        repository = Repository.objects.filter(pk=pk, organization=organization).first()
        if repository is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        repository.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
