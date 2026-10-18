from django.db import models

from apps.repos.models import Repository


class PullRequest(models.Model):
    """A pull request CodeSage has seen via webhook.

    Created in phase 2 so the acknowledgement comment's id has somewhere to live:
    phase 5's synthesis agent edits that same comment into the final review rather
    than adding a second one (spec section 13). `Review` and `ReviewFinding` arrive in
    phase 4.
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
    # The bot's comment on this PR. Phase 5 edits it in place.
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
