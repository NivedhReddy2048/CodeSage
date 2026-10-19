from django.urls import path

from apps.analytics.views import AnalyticsOverviewView

urlpatterns = [
    path("analytics/overview/", AnalyticsOverviewView.as_view(), name="analytics-overview"),
    # The spec's per-repository path (section 8): the same view, narrowed.
    path(
        "repos/<int:pk>/findings/analytics/",
        AnalyticsOverviewView.as_view(),
        name="repository-analytics",
    ),
]
