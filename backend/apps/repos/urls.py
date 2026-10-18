from django.urls import path

from apps.repos.views import (
    GitHubWebhookView,
    InstallableRepositoryListView,
    RepositoryConnectView,
    RepositoryDetailView,
    RepositoryListView,
)

urlpatterns = [
    path("webhooks/github/", GitHubWebhookView.as_view(), name="github-webhook"),
    path("repos/", RepositoryListView.as_view(), name="repository-list"),
    path(
        "repos/installable/",
        InstallableRepositoryListView.as_view(),
        name="repository-installable",
    ),
    path("repos/connect/", RepositoryConnectView.as_view(), name="repository-connect"),
    path("repos/<int:pk>/", RepositoryDetailView.as_view(), name="repository-detail"),
]
