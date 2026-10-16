from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.views import (
    CurrentUserView,
    GitHubCallbackView,
    GitHubLoginStartView,
    OrganizationListView,
)

urlpatterns = [
    path("auth/github/start/", GitHubLoginStartView.as_view(), name="github-start"),
    path("auth/github/callback/", GitHubCallbackView.as_view(), name="github-callback"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/me/", CurrentUserView.as_view(), name="current-user"),
    path("orgs/", OrganizationListView.as_view(), name="organization-list"),
]
