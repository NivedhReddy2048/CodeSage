"""Run a review for a pull request and persist the result.

This module owns everything the agents package deliberately does not: Django ORM
access, GitHub API calls, and turning settings into a `ReviewConfig`.
"""

import logging

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.agents import run_review
from apps.agents.types import RepoContext, ReviewConfig
from apps.repos import github_app
from apps.repos.github_app import API_HEADERS, GitHubAppError
from apps.reviews import comment as comment_renderer
from apps.reviews.models import LLMCall, Review, ReviewFinding
from apps.reviews.pricing import estimate_usd, to_inr, unpriced_models

logger = logging.getLogger(__name__)

API_ROOT = "https://api.github.com"
DIFF_TIMEOUT = 60


class DiffFetchError(Exception):
    """The pull request diff could not be retrieved."""


def build_config():
    """Translate Django settings into the agents package's plain config object."""
    return ReviewConfig(
        groq_api_key=settings.GROQ_API_KEY,
        gemini_api_key=settings.GEMINI_API_KEY,
        primary_model=settings.REVIEW_PRIMARY_MODEL,
        fallback_model=settings.REVIEW_FALLBACK_MODEL,
        request_timeout=settings.REVIEW_REQUEST_TIMEOUT,
        max_retries=settings.REVIEW_MAX_RETRIES,
        backoff_seconds=settings.REVIEW_BACKOFF_SECONDS,
        max_diff_bytes=settings.REVIEW_MAX_DIFF_BYTES,
        max_findings=settings.REVIEW_MAX_FINDINGS,
        breaker_failure_threshold=settings.REVIEW_BREAKER_FAILURE_THRESHOLD,
        breaker_reset_seconds=settings.REVIEW_BREAKER_RESET_SECONDS,
    )


def fetch_diff(installation_id, full_name, pr_number):
    """The PR's unified diff, via the App installation token.

    Uses the `.diff` media type rather than assembling it from the files API: it is
    one request and it is exactly the format the reviewer expects.
    """
    token = github_app.get_installation_token(installation_id)
    try:
        response = requests.get(
            f"{API_ROOT}/repos/{full_name}/pulls/{pr_number}",
            headers={
                **API_HEADERS,
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3.diff",
            },
            timeout=DIFF_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise DiffFetchError(f"Could not reach GitHub: {exc}") from exc

    if response.status_code != 200:
        raise DiffFetchError(
            f"Could not fetch the diff for {full_name}#{pr_number}: HTTP {response.status_code}"
        )
    return response.text


def review_pull_request(pull_request, installation_id):
    """Review one pull request and update the bot's comment.

    Always returns a Review row: a failed review is a recorded outcome with a
    message in the PR comment, never a traceback the user never sees.
    """
    repository = pull_request.repository

    review = Review.objects.create(
        pull_request=pull_request,
        status=Review.Status.RUNNING,
        head_sha=pull_request.head_sha,
        started_at=timezone.now(),
    )

    # Tell the PR which commit is being looked at before the slow part starts.
    _update_comment(pull_request, installation_id, comment_renderer.render_running(review.head_sha))

    try:
        diff = fetch_diff(installation_id, repository.full_name, pull_request.number)
    except (DiffFetchError, GitHubAppError) as exc:
        return _finish_failed(review, pull_request, installation_id, str(exc))

    context = RepoContext(
        full_name=repository.full_name,
        pr_number=pull_request.number,
        pr_title=pull_request.title,
        base_branch=pull_request.base_branch,
        head_sha=pull_request.head_sha,
    )

    result = run_review(diff, context, build_config())

    with transaction.atomic():
        _store_calls(review, result.calls)
        _store_totals(review, result)
        findings = _store_findings(review, result.findings)

    unpriced = unpriced_models(result.calls)

    if result.succeeded:
        body = comment_renderer.render(review, findings, unpriced=unpriced)
    else:
        body = comment_renderer.render(
            review, [], failure_reason=result.failure_reason, unpriced=unpriced
        )

    _update_comment(pull_request, installation_id, body)
    return review


def _store_calls(review, calls):
    LLMCall.objects.bulk_create(
        [
            LLMCall(
                review=review,
                provider=call.provider,
                model=call.model,
                input_tokens=call.input_tokens,
                output_tokens=call.output_tokens,
                latency_ms=call.latency_ms,
                succeeded=call.succeeded,
                is_fallback=call.is_fallback,
                error=call.error,
            )
            for call in calls
        ]
    )


def _store_totals(review, result):
    usd = estimate_usd(result.calls)

    review.status = Review.Status.DONE if result.succeeded else Review.Status.FAILED
    review.model_used = result.model_used
    review.used_fallback = result.used_fallback
    review.total_input_tokens = sum(c.input_tokens for c in result.calls)
    review.total_output_tokens = sum(c.output_tokens for c in result.calls)
    review.duration_ms = result.duration_ms
    review.estimated_cost_usd = usd
    review.estimated_cost_inr = to_inr(usd)
    review.truncated = result.truncated
    review.skipped_files = list(result.skipped_files)
    review.error = result.failure_reason[:2000] if result.failure_reason else ""
    review.finished_at = timezone.now()
    review.save()


def _store_findings(review, findings):
    rows = [
        ReviewFinding(
            review=review,
            agent=finding.agent,
            severity=str(finding.severity),
            category=str(finding.category),
            file_path=finding.file,
            line=finding.line,
            message=finding.message,
        )
        for finding in findings
    ]
    ReviewFinding.objects.bulk_create(rows)
    return rows


def _finish_failed(review, pull_request, installation_id, reason):
    review.status = Review.Status.FAILED
    review.error = reason[:2000]
    review.finished_at = timezone.now()
    review.save()

    _update_comment(
        pull_request,
        installation_id,
        comment_renderer.render(review, [], failure_reason=reason),
    )
    return review


def _update_comment(pull_request, installation_id, body):
    """Edit the bot's existing comment, or create one if it is somehow missing.

    Editing rather than appending is the whole point: a PR with five pushes should
    carry one bot comment, not five.
    """
    repository = pull_request.repository

    try:
        if pull_request.ack_comment_id:
            github_app.update_issue_comment(
                installation_id,
                repository.full_name,
                pull_request.ack_comment_id,
                body,
            )
            return

        created = github_app.create_issue_comment(
            installation_id, repository.full_name, pull_request.number, body
        )
        comment_id = created.get("id")
        if comment_id:
            pull_request.ack_comment_id = comment_id
            pull_request.save(update_fields=["ack_comment_id", "updated_at"])
    except GitHubAppError:
        # The review itself is already stored; failing to post it is worth logging
        # but must not lose the result.
        logger.exception(
            "Could not update the review comment on %s#%s",
            repository.full_name,
            pull_request.number,
        )
