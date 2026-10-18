from django.db import models

from apps.repos.models import Repository


class PullRequest(models.Model):
    """A pull request CodeSage has seen via webhook.

    Created in phase 2 so the acknowledgement comment's id has somewhere to live:
    phase 5's synthesis agent edits that same comment into the final review rather
    than adding a second one (spec section 13).
    """

    repository = models.ForeignKey(
        Repository, on_delete=models.CASCADE, related_name="pull_requests"
    )
    number = models.IntegerField()
    github_id = models.BigIntegerField(null=True, blank=True)
    title = models.CharField(max_length=1024, blank=True)
    author_login = models.CharField(max_length=255, blank=True)
    # Updated on every `synchronize`, so it always names the commit last reviewed.
    head_sha = models.CharField(max_length=64, blank=True)
    base_branch = models.CharField(max_length=255, blank=True)
    state = models.CharField(max_length=20, blank=True)
    # The bot's comment on this PR. Edited in place rather than duplicated.
    ack_comment_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["repository", "number"], name="unique_pr_number_per_repository"
            )
        ]
        ordering = ["-number"]

    def __str__(self):
        return f"{self.repository.full_name}#{self.number}"


class Review(models.Model):
    """One review run over one commit of a pull request."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    pull_request = models.ForeignKey(PullRequest, on_delete=models.CASCADE, related_name="reviews")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    # The commit actually reviewed. Shown in the comment so a reader can tell
    # whether the review covers the latest push.
    head_sha = models.CharField(max_length=64, blank=True)

    model_used = models.CharField(max_length=128, blank=True)
    used_fallback = models.BooleanField(default=False)

    # Denormalised from the per-call rows below, so the phase 6 dashboard can
    # aggregate without walking every call (spec section 14).
    total_input_tokens = models.IntegerField(default=0)
    total_output_tokens = models.IntegerField(default=0)
    duration_ms = models.IntegerField(default=0)
    estimated_cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    estimated_cost_inr = models.DecimalField(max_digits=12, decimal_places=4, default=0)

    # Reported in the comment, so a short review is never mistaken for a thorough one.
    truncated = models.BooleanField(default=False)
    skipped_files = models.JSONField(default=list, blank=True)

    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["pull_request", "-created_at"])]

    def __str__(self):
        return f"Review of {self.pull_request} ({self.status})"

    @property
    def duration_seconds(self):
        return self.duration_ms / 1000 if self.duration_ms else 0


class ReviewFinding(models.Model):
    """One defect reported by one agent, anchored to a real line."""

    class Severity(models.TextChoices):
        BLOCKING = "blocking", "Blocking"
        NIT = "nit", "Nit"

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="findings")
    # Named so phase 5 can attribute a finding to one of the six agents; v1 only
    # ever writes "review".
    agent = models.CharField(max_length=64, default="review")
    severity = models.CharField(max_length=20, choices=Severity.choices)
    category = models.CharField(max_length=40, blank=True)
    file_path = models.CharField(max_length=1024)
    line = models.IntegerField()
    message = models.TextField()
    # Phase 5's grounding agent fills this with a (file, line_range) from a
    # retrieved chunk. Blank in v1, which reviews the diff alone.
    citation = models.CharField(max_length=512, blank=True)
    dismissed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["file_path", "line"]

    def __str__(self):
        return f"{self.file_path}:{self.line} ({self.severity})"


class LLMCall(models.Model):
    """Telemetry for one provider call (spec section 14).

    One row per call, including failures and retries: the gap between calls and
    successful reviews is what shows how often the free tier is actually degrading.
    """

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="calls")
    provider = models.CharField(max_length=40)
    model = models.CharField(max_length=128)
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    latency_ms = models.IntegerField(default=0)
    succeeded = models.BooleanField(default=False)
    is_fallback = models.BooleanField(default=False)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.provider}/{self.model} ({self.latency_ms}ms)"
