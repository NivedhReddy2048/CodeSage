"""Re-run the review of one pull request, now, in this process.

    python manage.py rerun_review NivedhReddy2048/codesage-testbed 3

The webhook path is idempotent on GitHub's delivery id, so redelivering an event
does nothing - by design. This command deliberately goes around that: it creates
no WebhookEvent and never consults a delivery id. It refreshes the PR's head from
GitHub, then runs the same `review_pull_request` the Celery task runs, so the
summary comment is edited in place and inline comments are deduplicated exactly as
they are for a webhook-triggered review.

Runs synchronously, without the worker: useful when the worker is down, after
changing pipeline code (the worker does not reload), or to re-review after quota
returns.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.audit.services import Action
from apps.audit.services import record as audit
from apps.repos.github_app import GitHubAppError
from apps.repos.models import Repository
from apps.reviews.models import Review
from apps.reviews.rerun import refresh_pull_request
from apps.reviews.services import review_pull_request


class Command(BaseCommand):
    help = "Re-run the CodeSage review of a pull request (bypasses webhook delivery dedupe)."

    def add_arguments(self, parser):
        parser.add_argument("repo", help="Repository full name, e.g. owner/name")
        parser.add_argument("pr_number", type=int)

    def handle(self, *args, repo, pr_number, **options):
        repository = self._repository(repo)
        installation_id = repository.installation.installation_id

        try:
            pull_request = refresh_pull_request(repository, pr_number)
        except GitHubAppError as exc:
            raise CommandError(f"Could not read {repo}#{pr_number} from GitHub: {exc}") from exc

        self.stdout.write(
            f"Reviewing {repository.full_name}#{pr_number} at {pull_request.head_sha[:7]}..."
        )

        review = review_pull_request(pull_request, installation_id, trigger=Review.Trigger.RERUN)
        audit(
            repository.organization,
            None,
            Action.REVIEW_RERUN,
            target=pull_request,
            target_label=f"{repository.full_name}#{pr_number}",
            new_review=review.pk,
            head_sha=pull_request.head_sha,
            source="manage.py rerun_review",
        )
        pull_request.refresh_from_db()

        self.stdout.write(
            f"Review {review.pk}: {review.status}"
            f"{' (degraded)' if review.degraded else ''} in {review.duration_ms} ms, "
            f"model {review.model_used or '-'}"
            f"{' (fallback)' if review.used_fallback else ''}, "
            f"{review.findings.count()} findings"
        )
        if review.error:
            self.stdout.write(f"Error (not shown publicly): {review.error[:500]}")

        for run in review.agent_runs.all():
            status = "skipped" if run.skipped_reason else ("ok" if run.succeeded else "failed")
            served = run.model or "-"
            if run.used_fallback and run.requested_model:
                served += f" (fallback for {run.requested_model})"
            self.stdout.write(
                f"  {run.name:16} {status:8} {run.provider or '-':7} {served}  "
                f"{run.detail or run.skipped_reason or run.error[:120]}"
            )

        base = f"https://github.com/{repository.full_name}/pull/{pr_number}"
        if pull_request.ack_comment_id:
            self.stdout.write(f"Comment: {base}#issuecomment-{pull_request.ack_comment_id}")
        self.stdout.write(f"Files changed: {base}/files")

    def _repository(self, full_name):
        matches = list(
            Repository.objects.filter(full_name__iexact=full_name, installation__isnull=False)
        )
        if not matches:
            raise CommandError(f"No connected repository named {full_name} with an installation.")
        if len(matches) > 1:
            raise CommandError(
                f"{full_name} is connected by {len(matches)} organisations; "
                "this command reviews one repository record at a time."
            )
        return matches[0]
