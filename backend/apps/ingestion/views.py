import logging

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ingestion.models import CodeChunk
from apps.ingestion.serializers import IngestionJobSerializer, IngestionStatusSerializer
from apps.ingestion.services import active_job, latest_job, start_ingestion
from apps.repos import services as repo_services
from apps.repos.models import Repository

logger = logging.getLogger(__name__)


class RepositoryScopedView(APIView):
    """Resolves a repository within the caller's organisation, or 404s.

    Scoped lookup, never by primary key alone: another tenant's repository must read
    as absent rather than forbidden, which is the same rule the repos API follows.
    """

    permission_classes = [IsAuthenticated]

    def get_repository(self, request, pk):
        organization = repo_services.current_organization(request.user)
        if organization is None:
            return None
        return Repository.objects.filter(pk=pk, organization=organization).first()


class IngestionStatusView(RepositoryScopedView):
    """Latest indexing job for a repository. Polled by the UI while a job runs."""

    @extend_schema(
        responses={
            200: IngestionStatusSerializer,
            404: OpenApiResponse(description="Not connected to your organisation."),
        },
        description=(
            "The most recent ingestion job for this repository, with progress "
            "counters, plus how many chunks are currently stored."
        ),
    )
    def get(self, request, pk):
        repository = self.get_repository(request, pk)
        if repository is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        job = latest_job(repository)
        chunks = CodeChunk.objects.filter(repository=repository)

        return Response(
            {
                "job": IngestionJobSerializer(job).data if job else None,
                "chunk_count": chunks.count(),
                "indexed_files": chunks.values("file_path").distinct().count(),
            }
        )


class RepositoryReindexView(RepositoryScopedView):
    """Queue an indexing job on demand."""

    @extend_schema(
        request=None,
        responses={
            202: IngestionJobSerializer,
            200: IngestionJobSerializer,
            403: OpenApiResponse(description="Requires the owner or admin role."),
            404: OpenApiResponse(description="Not connected to your organisation."),
        },
        description=(
            "Starts indexing this repository. If a job is already pending or "
            "running, returns that job with 200 rather than queueing a second one."
        ),
    )
    def post(self, request, pk):
        repository = self.get_repository(request, pk)
        if repository is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            repo_services.require_management_role(request.user, repository.organization)
        except repo_services.PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)

        running = active_job(repository)
        if running:
            # Not an error: the user pressed the button twice, or a job is still
            # going. Returning the existing job keeps the UI on the same object.
            return Response(IngestionJobSerializer(running).data, status=status.HTTP_200_OK)

        job, started = start_ingestion(repository)
        return Response(
            IngestionJobSerializer(job).data,
            status=status.HTTP_202_ACCEPTED if started else status.HTTP_200_OK,
        )
