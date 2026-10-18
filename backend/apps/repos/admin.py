from django.contrib import admin

from apps.repos.models import AppInstallation, Repository, WebhookEvent


@admin.register(AppInstallation)
class AppInstallationAdmin(admin.ModelAdmin):
    list_display = [
        "account_login",
        "installation_id",
        "repository_selection",
        "organization",
        "suspended",
    ]
    list_filter = ["repository_selection", "suspended"]
    search_fields = ["account_login", "installation_id"]


@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):
    list_display = ["full_name", "organization", "default_branch", "private", "created_at"]
    list_filter = ["private"]
    search_fields = ["full_name", "owner", "name"]
    autocomplete_fields = ["organization"]


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = [
        "delivery_id",
        "event",
        "action",
        "repository_full_name",
        "received_at",
        "processed_at",
    ]
    list_filter = ["event", "action"]
    search_fields = ["delivery_id", "repository_full_name"]
    # The payload is large and immutable; viewing it is fine, editing is not.
    readonly_fields = ["payload", "received_at"]
