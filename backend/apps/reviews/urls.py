from django.urls import path

from apps.reviews.views import RepositoryReviewListView, ReviewDetailView

urlpatterns = [
    path("reviews/<int:pk>/", ReviewDetailView.as_view(), name="review-detail"),
    path(
        "repos/<int:pk>/reviews/",
        RepositoryReviewListView.as_view(),
        name="repository-review-list",
    ),
]
