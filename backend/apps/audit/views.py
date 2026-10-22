from datetime import datetime, time

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
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
                "action",
                OpenApiTypes.STR,
                description="Exact action (repo.connected), or a group (auth)",
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

        action = params.get("action")
        if action and "." not in action:
            # A group: "auth" is every auth.* event (signed in, out, failed).
            queryset = queryset.filter(action__startswith=f"{action}.")
        elif action:
            queryset = queryset.filter(action=action)
        if params.get("actor"):
            queryset = queryset.filter(actor_login__iexact=params["actor"])
        if params.get("q"):
            queryset = queryset.filter(target_label__icontains=params["q"])
        since = _bound(params.get("since"), time.min)
        if since:
            queryset = queryset.filter(created_at__gte=since)
        until = _bound(params.get("until"), time.max)
        if until:
            queryset = queryset.filter(created_at__lte=until)
        return queryset


def _bound(value, time_of_day):
    """A datetime, or a bare date (what a browser date input sends) widened to the
    start or end of that day.

    The date is tried first: on Python 3.11+ `parse_datetime` also accepts a bare
    date and returns midnight, so `until=<today>` excluded everything after 00:00.
    `parse_date` rejects anything with a time, so real datetimes still fall through.
    """
    if not value:
        return None
    try:
        day = parse_date(value)
    except ValueError:
        day = None
    if day:
        return timezone.make_aware(datetime.combine(day, time_of_day))
    try:
        return parse_datetime(value)
    except ValueError:
        return None
