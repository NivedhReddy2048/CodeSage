from django.db.models import Count
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.repos import services as repo_services
from apps.reviews.models import Review
from apps.reviews.serializers import ReviewSerializer, ReviewSummarySerializer


def _visible_reviews(user):
    """Reviews belonging to the caller's organisation.

    Scoped at the queryset, never by primary key alone: this is the tenancy
    boundary, and another tenant's review must read as absent rather than forbidden.
    """
    organization = repo_services.current_organization(user)
    if organization is None:
        return Review.objects.none()
    return Review.objects.filter(
        pull_request__repository__organization=organization
    ).select_related("pull_request", "pull_request__repository")


class ReviewDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: ReviewSerializer,
            404: OpenApiResponse(description="No such review in your organisation."),
        },
        description="A review with its findings and per-call cost and latency.",
    )
    def get(self, request, pk):
        review = (
            _visible_reviews(request.user)
            .prefetch_related("findings", "calls")
            .filter(pk=pk)
            .first()
        )
        if review is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(ReviewSerializer(review).data)


class RepositoryReviewListView(ListAPIView):
    """Reviews for one repository, newest first."""

    serializer_class = ReviewSummarySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        return (
            _visible_reviews(self.request.user)
            .filter(pull_request__repository_id=self.kwargs["pk"])
            .annotate(finding_count=Count("findings"))
            .order_by("-created_at")[:50]
        )
