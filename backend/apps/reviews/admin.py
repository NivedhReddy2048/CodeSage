from django.contrib import admin

from apps.reviews.models import ReviewRawFinding


@admin.register(ReviewRawFinding)
class ReviewRawFindingAdmin(admin.ModelAdmin):
    """The pre-synthesis record, for answering "where did this finding come from?"."""

    list_display = ("review", "agent", "file_path", "line", "cited_line", "severity", "outcome")
    list_filter = ("agent", "outcome", "severity")
    search_fields = ("message", "file_path", "rule")
    raw_id_fields = ("review", "final")
