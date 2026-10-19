from django.utils import timezone
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notifications.models import Notification
from apps.repos import services as repo_services

LIST_LIMIT = 30


class NotificationSerializer(serializers.ModelSerializer):
    read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ["id", "kind", "title", "body", "link", "read", "read_at", "created_at"]
        read_only_fields = fields

    def get_read(self, notification) -> bool:
        return notification.read_at is not None


class NotificationListResponseSerializer(serializers.Serializer):
    unread_count = serializers.IntegerField()
    results = NotificationSerializer(many=True)


def _mine(user):
    """The caller's own notifications in their current organisation, nobody else's."""
    organization = repo_services.current_organization(user)
    if organization is None:
        return Notification.objects.none()
    return Notification.objects.filter(recipient=user, organization=organization)


class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: NotificationListResponseSerializer},
        description="The caller's latest notifications and their unread count.",
    )
    def get(self, request):
        mine = _mine(request.user)
        return Response(
            {
                "unread_count": mine.filter(read_at__isnull=True).count(),
                "results": NotificationSerializer(mine[:LIST_LIMIT], many=True).data,
            }
        )


class NotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            200: NotificationSerializer,
            404: OpenApiResponse(description="Not one of your notifications."),
        },
    )
    def post(self, request, pk):
        notification = _mine(request.user).filter(pk=pk).first()
        if notification is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at"])
        return Response(NotificationSerializer(notification).data)


class NotificationReadAllView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: OpenApiResponse(description="{'marked': n}")})
    def post(self, request):
        marked = _mine(request.user).filter(read_at__isnull=True).update(read_at=timezone.now())
        return Response({"marked": marked})
