"""Mark reviews that earlier re-runs created as re-runs.

`Review.trigger` arrived after some re-runs had already happened, and those rows
defaulted to "webhook". Every re-run - from the UI or `manage.py rerun_review` - has
always written an audit entry naming the review it created (`new_review`), so the
history is recoverable rather than guessed.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    AuditLogEntry = apps.get_model("audit", "AuditLogEntry")
    Review = apps.get_model("reviews", "Review")

    rerun_ids = set()
    for metadata in AuditLogEntry.objects.filter(action="review.rerun").values_list(
        "metadata", flat=True
    ):
        new_review = (metadata or {}).get("new_review")
        if isinstance(new_review, int):
            rerun_ids.add(new_review)
    if rerun_ids:
        Review.objects.filter(pk__in=rerun_ids).update(trigger="rerun")


class Migration(migrations.Migration):
    dependencies = [
        ("reviews", "0009_review_trigger"),
        ("audit", "0001_initial"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
