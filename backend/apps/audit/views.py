from django.utils.dateparse import parse_datetime
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.audit.models import AuditLogEntry
from apps.repos import services as repo_services


class AuditLogEntrySerializer(serializers.ModelSerializer):
    action_label = serializers.CharField(source="get_action_display", read_only=True)

    class Meta:
        model = AuditLogEntry
        fields = [
            "id",
            "action",
            "action_label",
            "actor_login",
            "target_type",
            "target_id",
            "target_label",
            "metadata",
            "created_at",
        ]
        read_only_fields = fields


class AuditPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


class AuditLogView(ListAPIView):
    """The organisation's audit trail. Owners and admins only.

    Scoped to the caller's current organisation at the queryset, so another tenant's
    entries can never appear, whatever filters are passed.
    """

    serializer_class = AuditLogEntrySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = AuditPagination

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "action", OpenApiTypes.STR, description="Exact action, e.g. repo.connected"
            ),
            OpenApiParameter("actor", OpenApiTypes.STR, description="Actor GitHub login"),
            OpenApiParameter("q", OpenApiTypes.STR, description="Search the target label"),
            OpenApiParameter("since", OpenApiTypes.DATETIME),
            OpenApiParameter("until", OpenApiTypes.DATETIME),
        ],
        description="Append-only audit trail for the caller's organisation (owner/admin).",
    )
    def get(self, request, *args, **kwargs):
        organization = repo_services.current_organization(request.user)
        try:
            repo_services.require_management_role(request.user, organization)
        except repo_services.PermissionDenied:
            return Response(
                {"detail": "The audit log requires the owner or admin role."},
                status=status.HTTP_403_FORBIDDEN,
            )
        self.organization = organization
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = AuditLogEntry.objects.filter(organization=self.organization)
        params = self.request.query_params

        if params.get("action"):
            queryset = queryset.filter(action=params["action"])
        if params.get("actor"):
            queryset = queryset.filter(actor_login__iexact=params["actor"])
        if params.get("q"):
            queryset = queryset.filter(target_label__icontains=params["q"])
        since = parse_datetime(params.get("since") or "")
        if since:
            queryset = queryset.filter(created_at__gte=since)
        until = parse_datetime(params.get("until") or "")
        if until:
            queryset = queryset.filter(created_at__lte=until)
        return queryset
