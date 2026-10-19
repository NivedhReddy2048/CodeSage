from django.contrib import admin

from apps.notifications.models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["created_at", "organization", "recipient", "kind", "title", "read_at"]
    list_filter = ["kind"]
