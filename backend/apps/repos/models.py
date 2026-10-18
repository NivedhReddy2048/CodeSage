from django.conf import settings
from django.db import models

from apps.accounts.models import Organization


class AppInstallation(models.Model):
    """A GitHub App installation on a user or organisation account.

    The installation is the unit GitHub scopes access tokens to: one token per
    installation, valid an hour, able to touch only the repositories selected during
    install. We mirror it here so a `Repository` can be traced back to the credential
    that reaches it.
    """

    class RepositorySelection(models.TextChoices):
        ALL = "all", "All repositories"
        SELECTED = "selected", "Selected repositories"

    installation_id = models.BigIntegerField(unique=True)
    account_login = models.CharField(max_length=255)
    account_type = models.CharField(max_length=20, blank=True)
    repository_selection = models.CharField(
        max_length=20, choices=RepositorySelection.choices, blank=True
    )
    # Set when a CodeSage user connects a repository from this installation. Null
    # until then: GitHub can deliver an `installation` webhook before anyone has
    # linked it to a tenant.
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="github_installations",
        null=True,
        blank=True,
    )
    suspended = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["account_login"]

    def __str__(self):
        return f"{self.account_login} (installation {self.installation_id})"


class Repository(models.Model):
    """A connected GitHub repository, owned by one of our organisations."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="repositories"
    )
    installation = models.ForeignKey(
        AppInstallation,
        on_delete=models.SET_NULL,
        related_name="repositories",
        null=True,
        blank=True,
    )
    github_id = models.BigIntegerField()
    full_name = models.CharField(max_length=512)
    owner = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    default_branch = models.CharField(max_length=255, default="main")
    private = models.BooleanField(default=False)
    connected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="connected_repositories",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # Scoped per organisation rather than globally unique: two tenants may
            # legitimately connect the same public repository.
            models.UniqueConstraint(
                fields=["organization", "github_id"], name="unique_repo_per_organization"
            )
        ]
        ordering = ["full_name"]
        verbose_name_plural = "repositories"

    def __str__(self):
        return self.full_name


class WebhookEvent(models.Model):
    """A received GitHub webhook delivery, stored before any work is done on it.

    Persisting the raw payload makes a failed review replayable without asking GitHub
    to redeliver, and `delivery_id` being unique is what makes redelivery idempotent:
    GitHub reuses the id, so a second attempt collides instead of queueing a duplicate.
    """

    delivery_id = models.CharField(max_length=255, unique=True)
    event = models.CharField(max_length=64)
    action = models.CharField(max_length=64, blank=True)
    installation_id = models.BigIntegerField(null=True, blank=True)
    repository_full_name = models.CharField(max_length=512, blank=True)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
    # Stamped when the handler finishes acting on it, so unprocessed deliveries are
    # findable after a crash.
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]
        indexes = [models.Index(fields=["event", "action"])]

    def __str__(self):
        label = f"{self.event}.{self.action}" if self.action else self.event
        return f"{label} ({self.delivery_id})"
