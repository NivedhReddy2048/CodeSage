from django.conf import settings
from django.db import models

from apps.accounts.models import Organization


class AppendOnlyError(Exception):
    """An audit entry was about to be changed or deleted."""


class AuditLogQuerySet(models.QuerySet):
    """Refuses bulk changes. `update()` and `delete()` would rewrite history."""

    def update(self, **kwargs):
        raise AppendOnlyError("Audit log entries cannot be updated.")

    def delete(self):
        raise AppendOnlyError("Audit log entries cannot be deleted.")


class AuditLogEntry(models.Model):
    """One action someone took in an organisation. Written once, never edited.

    Append-only is enforced in the model rather than promised: `save()` refuses an
    existing row, `delete()` refuses outright, and the queryset blocks bulk update
    and delete. An audit trail anyone can quietly rewrite is not one. Rows still go
    when their organisation is deleted (CASCADE); that is the tenant leaving, not an
    edit to its history.
    """

    class Action(models.TextChoices):
        REPO_CONNECTED = "repo.connected", "Repository connected"
        REPO_DISCONNECTED = "repo.disconnected", "Repository disconnected"
        REPO_REINDEXED = "repo.reindexed", "Re-index requested"
        REVIEW_RERUN = "review.rerun", "Review re-run"
        MEMBER_ROLE_CHANGED = "member.role_changed", "Member role changed"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="audit_entries"
    )
    # SET_NULL: removing a user must not erase what they did. The login is copied
    # into `actor_login` so the entry still reads correctly afterwards.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    actor_login = models.CharField(max_length=150, blank=True)
    action = models.CharField(max_length=64, choices=Action.choices)
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    target_label = models.CharField(max_length=512, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = AuditLogQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["organization", "-created_at"])]
        verbose_name_plural = "audit log entries"

    def __str__(self):
        return f"{self.actor_login or 'system'} {self.action} {self.target_label}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise AppendOnlyError("Audit log entries cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Audit log entries cannot be deleted.")
