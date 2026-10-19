from django.db.models import Count, Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.repos import services as repo_services
from apps.reviews import progress
from apps.reviews.models import Review
from apps.reviews.rerun import RerunRefused, request_rerun
from apps.reviews.serializers import (
    ReviewListSerializer,
    ReviewSerializer,
    ReviewSummarySerializer,
)


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


def _can_manage(user):
    organization = repo_services.current_organization(user)
    return repo_services.role_in(user, organization) in repo_services.REPO_MANAGEMENT_ROLES


class ReviewPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


class ReviewListView(ListAPIView):
    """Every review in the caller's organisation, newest first, filterable."""

    serializer_class = ReviewListSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = ReviewPagination

    @extend_schema(
        parameters=[
            OpenApiParameter("repository", OpenApiTypes.INT),
            OpenApiParameter(
                "status",
                OpenApiTypes.STR,
                description="pending, running, done, failed, or degraded",
            ),
            OpenApiParameter(
                "severity",
                OpenApiTypes.STR,
                description="blocking or nit: reviews with at least one such finding",
            ),
        ]
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        params = self.request.query_params
        queryset = _visible_reviews(self.request.user)

        if params.get("repository", "").isdigit():
            queryset = queryset.filter(pull_request__repository_id=int(params["repository"]))

        wanted = params.get("status")
        if wanted == "degraded":
            queryset = queryset.filter(degraded=True)
        elif wanted in Review.Status.values:
            queryset = queryset.filter(status=wanted)

        severity = params.get("severity")
        if severity in ("blocking", "nit"):
            queryset = queryset.filter(findings__severity=severity)

        return (
            queryset.annotate(
                finding_count=Count("findings", distinct=True),
                blocking_count=Count(
                    "findings", filter=Q(findings__severity="blocking"), distinct=True
                ),
                nit_count=Count("findings", filter=Q(findings__severity="nit"), distinct=True),
            )
            .distinct()
            .order_by("-created_at", "-id")
        )


class ReviewDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: ReviewSerializer,
            404: OpenApiResponse(description="No such review in your organisation."),
        },
        description=(
            "A review with its findings and per-call cost and latency. Raw error text "
            "is included only for owners and admins; everyone gets `error_summary`."
        ),
    )
    def get(self, request, pk):
        review = (
            _visible_reviews(request.user)
            .prefetch_related("findings", "calls", "agent_runs")
            .filter(pk=pk)
            .first()
        )
        if review is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        context = {"show_error_details": _can_manage(request.user)}
        return Response(ReviewSerializer(review, context=context).data)


class ReviewStatusView(APIView):
    """Poll fallback for the progress WebSocket: the same snapshot it sends first."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: OpenApiResponse(description="Status, per-agent state and N/total complete."),
            404: OpenApiResponse(description="No such review in your organisation."),
        }
    )
    def get(self, request, pk):
        review = _visible_reviews(request.user).filter(pk=pk).first()
        if review is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(progress.snapshot(review))


class ReviewDiffView(APIView):
    """The unified diff this review read, for the diff viewer.

    Stored at review time. A review from before the diff was stored is filled from
    GitHub's compare API at its exact head commit, then cached on the row, so the
    findings line up with the code that was actually reviewed - not with whatever
    the pull request looks like now.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: OpenApiResponse(description="{diff, source: stored|github, truncated, head_sha}"),
            404: OpenApiResponse(description="No such review in your organisation."),
            502: OpenApiResponse(description="The diff could not be fetched from GitHub."),
        }
    )
    def get(self, request, pk):
        import logging

        from apps.repos.github_app import GitHubAppError
        from apps.reviews.services import (
            MAX_STORED_DIFF_BYTES,
            DiffFetchError,
            fetch_compare_diff,
        )

        review = _visible_reviews(request.user).filter(pk=pk).first()
        if review is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        source = "stored"
        if not review.diff:
            pull_request = review.pull_request
            repository = pull_request.repository
            if not (review.head_sha and repository.installation):
                return Response(
                    {"detail": "No diff is available for this review."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            try:
                diff = fetch_compare_diff(
                    repository.installation.installation_id,
                    repository.full_name,
                    pull_request.base_branch or repository.default_branch,
                    review.head_sha,
                )
            except (DiffFetchError, GitHubAppError) as exc:
                logging.getLogger(__name__).warning("Diff for review %s: %s", pk, exc)
                return Response(
                    {"detail": "Could not fetch this diff from GitHub."},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            review.diff = diff[:MAX_STORED_DIFF_BYTES]
            review.save(update_fields=["diff"])
            source = "github"

        return Response(
            {
                "diff": review.diff,
                "source": source,
                "truncated": len(review.diff) >= MAX_STORED_DIFF_BYTES,
                "head_sha": review.head_sha,
            }
        )


class ReviewRerunView(APIView):
    """Queue a fresh review of this review's pull request. Owner/admin only."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={
            202: OpenApiResponse(description="Queued: {'review_id': <new pending review>}"),
            403: OpenApiResponse(description="Requires the owner or admin role."),
            404: OpenApiResponse(description="No such review in your organisation."),
            409: OpenApiResponse(description="A review of this PR is already in progress."),
        },
        description=(
            "Re-reviews the pull request at its current head. Deliberately bypasses "
            "webhook delivery-id dedupe, like `manage.py rerun_review`. Audit-logged."
        ),
    )
    def post(self, request, pk):
        review = _visible_reviews(request.user).filter(pk=pk).first()
        if review is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            repo_services.require_management_role(
                request.user, review.pull_request.repository.organization
            )
        except repo_services.PermissionDenied:
            return Response(
                {"detail": "Re-running a review requires the owner or admin role."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            fresh = request_rerun(review, request.user)
        except RerunRefused as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)

        return Response({"review_id": fresh.pk}, status=status.HTTP_202_ACCEPTED)


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
