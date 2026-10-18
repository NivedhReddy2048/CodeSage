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
    # Registered without the trailing slash too, because relays and proxies normalise
    # paths differently: smee-client strips it, and a POST to the slash-less path
    # cannot be rescued by APPEND_SLASH (Django refuses to redirect a POST, since the
    # body would be lost) — it raises, producing a 500 before any of our code runs.
    # Accepting both is more robust than depending on every client agreeing with us.
    path(
        "webhooks/github",
        GitHubWebhookView.as_view(),
        name="github-webhook-no-slash",
    ),
    path("repos/", RepositoryListView.as_view(), name="repository-list"),
    path(
        "repos/installable/",
        InstallableRepositoryListView.as_view(),
        name="repository-installable",
    ),
    path("repos/connect/", RepositoryConnectView.as_view(), name="repository-connect"),
    path("repos/<int:pk>/", RepositoryDetailView.as_view(), name="repository-detail"),
]
