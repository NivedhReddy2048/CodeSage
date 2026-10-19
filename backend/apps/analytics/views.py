from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.analytics.services import overview
from apps.repos import services as repo_services
from apps.repos.models import Repository

MAX_DAYS = 365


class AnalyticsOverviewView(APIView):
    """Dashboard KPIs, daily trend and breakdowns for the caller's organisation.

    Also served at the spec's `/api/repos/{id}/findings/analytics/`, which is this
    view narrowed to one repository.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter("days", OpenApiTypes.INT, description="Window, default 30, max 365"),
            OpenApiParameter("repository", OpenApiTypes.INT),
        ],
        responses={
            200: OpenApiResponse(description="summary, timeseries, by_category, by_agent"),
            404: OpenApiResponse(description="Repository not in your organisation."),
        },
        description="Costs are estimates at paid-tier rates; see `cost_basis`.",
    )
    def get(self, request, pk=None):
        organization = repo_services.current_organization(request.user)
        if organization is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            days = int(request.query_params.get("days", 30))
        except ValueError:
            days = 30
        days = max(1, min(days, MAX_DAYS))

        repository_id = pk
        param = request.query_params.get("repository", "")
        if repository_id is None and param.isdigit():
            repository_id = int(param)

        if repository_id is not None:
            # Scoped lookup: another tenant's repository reads as absent.
            if not Repository.objects.filter(pk=repository_id, organization=organization).exists():
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response(overview(organization, days=days, repository_id=repository_id))
