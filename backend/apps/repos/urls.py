from django.urls import path

from apps.repos.views import GitHubWebhookView

urlpatterns = [
    path("webhooks/github/", GitHubWebhookView.as_view(), name="github-webhook"),
]
