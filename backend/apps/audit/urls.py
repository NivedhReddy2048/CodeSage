from django.urls import path

from apps.audit.views import AuditLogView

urlpatterns = [
    path("audit-log/", AuditLogView.as_view(), name="audit-log"),
]
