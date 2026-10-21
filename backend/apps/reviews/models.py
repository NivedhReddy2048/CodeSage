from datetime import timedelta

from django.db import models
from django.utils import timezone

from apps.repos.models import Repository

# A review pending or running for longer than this is presumed dead: no worker picked
# it up, or the one that did crashed or was restarted mid-job. Such a review is shown
# as stalled, and no longer blocks a re-run.
STALE_AFTER = timedelta(minutes=15)


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

    # True when no model answered and only local analysis ran. Kept distinct from
    # `failed`: the pipeline completed, but what it produced is not a review, and
    # the comment says so rather than letting a thin lint pass pose as one.
    degraded = models.BooleanField(default=False)

    # Reported in the comment, so a short review is never mistaken for a thorough one.
    truncated = models.BooleanField(default=False)
    skipped_files = models.JSONField(default=list, blank=True)

    error = models.TextField(blank=True)
    # The unified diff this review read, so the review page can show findings on
    # the exact lines that were reviewed even after more commits land. Capped at
    # MAX_STORED_DIFF_BYTES; older reviews are filled from GitHub on first view.
    diff = models.TextField(blank=True)

    # Per-agent state while the pipeline runs: {"security": "running", ...}. What the
    # status endpoint and a (re)connecting WebSocket report, so neither has to have
    # been listening from the start.
    progress = models.JSONField(default=dict, blank=True)
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

    @property
    def stalled(self):
        """Still pending or running long after any real review would have finished."""
        return (
            self.status in {self.Status.PENDING, self.Status.RUNNING}
            and self.created_at is not None
            and self.created_at < timezone.now() - STALE_AFTER
        )


class ReviewFinding(models.Model):
    """One defect reported by one agent, anchored to a real line."""

    class Severity(models.TextChoices):
        BLOCKING = "blocking", "Blocking"
        NIT = "nit", "Nit"

    class Placement(models.TextChoices):
        # Mirrors apps.agents.types.Placement; decided by the anchoring step.
        INLINE = "inline", "On an added line"
        EXISTING = "existing", "Existing code"
        GENERAL = "general", "General"

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="findings")
    # Named so phase 5 can attribute a finding to one of the six agents; v1 only
    # ever writes "review".
    agent = models.CharField(max_length=64, default="review")
    severity = models.CharField(max_length=20, choices=Severity.choices)
    category = models.CharField(max_length=40, blank=True)
    file_path = models.CharField(max_length=1024)
    # For an inline finding this is the added line its comment is posted on, and the
    # summary shows the same number. For "existing" it is the unchanged line the
    # evidence matched; for "general" it is the model's guess, never shown.
    line = models.IntegerField()
    placement = models.CharField(max_length=16, choices=Placement.choices, default=Placement.INLINE)
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


class ReviewRawFinding(models.Model):
    """One finding exactly as an agent reported it, before synthesis.

    The review's audit trail. Without it, "why does the comment say (also flagged by
    static_analysis)?" had to be answered by replaying the pipeline: the raw findings
    were never stored. Each row is linked to the final finding it became, or says
    why it was dropped.
    """

    class Outcome(models.TextChoices):
        KEPT = "kept", "Kept"  # it is `final`
        MERGED = "merged", "Merged"  # folded into `final`
        DROPPED = "dropped", "Dropped"  # see `reason`

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="raw_findings")
    final = models.ForeignKey(
        ReviewFinding,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sources",
    )
    agent = models.CharField(max_length=64)
    # As the agent reported it, before the severity policy.
    severity = models.CharField(max_length=20, choices=ReviewFinding.Severity.choices)
    category = models.CharField(max_length=40, blank=True)
    file_path = models.CharField(max_length=1024)
    # The anchored line, and the line the agent itself named.
    line = models.IntegerField()
    cited_line = models.IntegerField()
    # Blank when the finding was dropped before it could be anchored.
    placement = models.CharField(max_length=16, blank=True)
    anchored_by = models.CharField(max_length=16, blank=True)
    rule = models.CharField(max_length=64, blank=True)
    evidence = models.TextField(blank=True)
    message = models.TextField()
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    reason = models.CharField(max_length=255, blank=True)
    # Why the severity policy lowered it, when it did.
    downgraded = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.agent} {self.file_path}:{self.line} ({self.outcome})"


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


class AgentRunRecord(models.Model):
    """Per-agent telemetry for one review (spec section 14).

    Separate from LLMCall because an agent is not the same thing as a call: static
    analysis makes none, a skipped agent makes none, and a retried agent makes two.
    Storing both lets the review page answer "what did each agent do" and "what did
    we spend" without conflating them.
    """

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="agent_runs")
    name = models.CharField(max_length=64)
    # The model that SERVED the agent's call, which after a failover is the
    # fallback's - cost and per-model analytics are based on this.
    model = models.CharField(max_length=128, blank=True)
    # The model the agent asked for. Differs from `model` only after a failover.
    requested_model = models.CharField(max_length=128, blank=True)
    provider = models.CharField(max_length=40, blank=True)
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    latency_ms = models.IntegerField(default=0)
    succeeded = models.BooleanField(default=False)
    used_fallback = models.BooleanField(default=False)
    findings_count = models.IntegerField(default=0)
    # Set when the agent never ran, e.g. the token budget was exhausted.
    skipped_reason = models.CharField(max_length=255, blank=True)
    error = models.TextField(blank=True)
    # For agents that are not a model call: e.g. which linters actually ran.
    detail = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.name} ({self.model or 'no model'})"
