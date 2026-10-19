from django.contrib import admin

from apps.audit.models import AuditLogEntry


@admin.register(AuditLogEntry)
class AuditLogEntryAdmin(admin.ModelAdmin):
    """Read-only: the admin must not become a way round append-only."""

    list_display = ["created_at", "organization", "actor_login", "action", "target_label"]
    list_filter = ["action"]
    search_fields = ["actor_login", "target_label"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
