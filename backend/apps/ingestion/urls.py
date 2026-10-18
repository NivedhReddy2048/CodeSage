from django.urls import path

from apps.ingestion.views import IngestionStatusView, RepositoryReindexView

urlpatterns = [
    path(
        "repos/<int:pk>/ingestion/",
        IngestionStatusView.as_view(),
        name="ingestion-status",
    ),
    path(
        "repos/<int:pk>/reindex/",
        RepositoryReindexView.as_view(),
        name="repository-reindex",
    ),
]
