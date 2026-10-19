from django.urls import path

from apps.reviews.views import (
    RepositoryReviewListView,
    ReviewDetailView,
    ReviewListView,
    ReviewRerunView,
    ReviewStatusView,
)

urlpatterns = [
    path("reviews/", ReviewListView.as_view(), name="review-list"),
    path("reviews/<int:pk>/", ReviewDetailView.as_view(), name="review-detail"),
    path("reviews/<int:pk>/status/", ReviewStatusView.as_view(), name="review-status"),
    path("reviews/<int:pk>/rerun/", ReviewRerunView.as_view(), name="review-rerun"),
    path(
        "repos/<int:pk>/reviews/",
        RepositoryReviewListView.as_view(),
        name="repository-review-list",
    ),
]
