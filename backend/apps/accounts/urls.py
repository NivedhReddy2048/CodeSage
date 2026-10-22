from django.urls import path

from apps.accounts.views import (
    AuditedTokenRefreshView,
    CurrentUserView,
    GitHubCallbackView,
    GitHubLoginStartView,
    LogoutView,
    MemberListView,
    MemberRoleView,
    OrganizationListView,
)

urlpatterns = [
    path("auth/github/start/", GitHubLoginStartView.as_view(), name="github-start"),
    path("auth/github/callback/", GitHubCallbackView.as_view(), name="github-callback"),
    path("auth/token/refresh/", AuditedTokenRefreshView.as_view(), name="token-refresh"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/me/", CurrentUserView.as_view(), name="current-user"),
    path("orgs/", OrganizationListView.as_view(), name="organization-list"),
    path("orgs/members/", MemberListView.as_view(), name="member-list"),
    path("orgs/members/<int:pk>/", MemberRoleView.as_view(), name="member-role"),
]
