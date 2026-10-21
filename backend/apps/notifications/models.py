from django.conf import settings
from django.db import models

from apps.accounts.models import Organization


class Notification(models.Model):
    """One in-app notification for one user in one organisation.

    Fanned out to each member when the event happens rather than stored once per
    organisation, so read state is per person: one admin reading it must not clear
    it for everyone else.
    """

    class Kind(models.TextChoices):
        REVIEW_FINISHED = "review.finished", "Review finished"
        REVIEW_DEGRADED = "review.degraded", "Review degraded"
        REVIEW_FAILED = "review.failed", "Review failed"
        INDEXING_FAILED = "indexing.failed", "Indexing failed"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="notifications"
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(max_length=40, choices=Kind.choices)
    title = models.CharField(max_length=255)
    body = models.CharField(max_length=500, blank=True)
    # A frontend route such as /reviews/12, so the bell can link straight to it.
    link = models.CharField(max_length=255, blank=True)
    # Structured context the UI renders beside the title: for a review, the full
    # repository name (the title shortens it), the head SHA and what triggered it.
    meta = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["recipient", "organization", "read_at"])]

    def __str__(self):
        return f"{self.kind} for {self.recipient}"
