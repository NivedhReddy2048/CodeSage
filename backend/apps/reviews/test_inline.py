"""Inline review comments: posted on the right lines, never twice."""

from types import SimpleNamespace
from unittest import mock

import pytest

from apps.agents.types import Finding, ReviewResult, Severity
from apps.repos.github_app import GitHubAppError
from apps.reviews.inline import MARKER, existing_locations, post_inline_comments
from apps.reviews.test_degraded import pull_request, run  # noqa: F401 - fixture reuse

HEAD = "abc1234def"


def finding(
    path="app/users.py",
    line=13,
    severity="blocking",
    message="SQL built from input.",
    placement="inline",
):
    return SimpleNamespace(
        file_path=path,
        line=line,
        severity=severity,
        category="security",
        message=message,
        agent="security",
        placement=placement,
    )


class FakeGitHub:
    """Records calls and remembers posted comments, like the real PR would."""

    def __init__(self, existing=(), reject_batch=False, reject_paths=()):
        self.comments = list(existing)
        self.reviews = []
        self.singles = []
        self.reject_batch = reject_batch
        self.reject_paths = set(reject_paths)

    def list_review_comments(self, installation_id, repo, number):
        return list(self.comments)

    def create_review(self, installation_id, repo, number, commit_id, body, comments):
        if self.reject_batch:
            raise GitHubAppError("422: line must be part of the diff")
        self.reviews.append({"commit_id": commit_id, "body": body, "comments": comments})
        self.comments.extend(comments)
        return {"id": 1}

    def create_review_comment(self, installation_id, repo, number, commit_id, comment):
        if comment["path"] in self.reject_paths:
            raise GitHubAppError("422: line must be part of the diff")
        self.singles.append(comment)
        self.comments.append(comment)
        return {"id": 2}


def pr():
    return SimpleNamespace(number=1, repository=SimpleNamespace(full_name="owner/repo"))


def test_findings_are_posted_as_one_review_on_the_right_lines():
    github = FakeGitHub()

    outcome = post_inline_comments(github, 1, pr(), HEAD, [finding(), finding(line=20)], 15)

    assert outcome.posted == 2
    (review,) = github.reviews
    assert review["commit_id"] == HEAD
    assert [(c["path"], c["line"], c["side"]) for c in review["comments"]] == [
        ("app/users.py", 13, "RIGHT"),
        ("app/users.py", 20, "RIGHT"),
    ]
    assert all(MARKER in c["body"] for c in review["comments"])
    assert "SQL built from input." in review["comments"][0]["body"]


def test_a_rerun_of_the_same_commit_posts_nothing_new():
    github = FakeGitHub()
    findings = [finding(), finding(line=20)]

    post_inline_comments(github, 1, pr(), HEAD, findings, 15)
    second = post_inline_comments(github, 1, pr(), HEAD, findings, 15)

    assert second.posted == 0
    assert second.duplicates == 2
    assert len(github.reviews) == 1
    assert len(github.comments) == 2


def test_dedupe_ignores_reworded_findings_on_the_same_line():
    """A model rephrases between runs; the location is what identifies a comment."""
    github = FakeGitHub()
    post_inline_comments(github, 1, pr(), HEAD, [finding(message="first wording")], 15)

    second = post_inline_comments(github, 1, pr(), HEAD, [finding(message="reworded")], 15)

    assert second.posted == 0


def test_dedupe_is_by_exact_line_now_that_anchors_are_exact():
    """Anchors come from quoted evidence, so a rerun lands on the same line.

    Dedupe used to treat anything within two lines as the same comment, to absorb a
    model's line jitter between runs (testbed PR #1: :3, then :1). That jitter is
    gone, and the window had a cost: a different finding on the next line was
    silently never posted.
    """
    github = FakeGitHub()
    post_inline_comments(github, 1, pr(), HEAD, [finding(line=3)], 15)

    rerun = post_inline_comments(github, 1, pr(), HEAD, [finding(line=3)], 15)
    neighbour = post_inline_comments(github, 1, pr(), HEAD, [finding(line=4)], 15)

    assert (rerun.posted, rerun.duplicates) == (0, 1)
    assert neighbour.posted == 1


def test_only_findings_on_added_lines_are_posted_inline():
    github = FakeGitHub()
    findings = [
        finding(line=3),
        finding(line=7, placement="existing"),
        finding(line=9, placement="general"),
    ]

    outcome = post_inline_comments(github, 1, pr(), HEAD, findings, 15)

    assert outcome.posted == 1
    assert [c["line"] for c in github.reviews[0]["comments"]] == [3]


def test_an_outdated_comment_does_not_block_a_fresh_one():
    """GitHub nulls `line` once the code under a comment has changed."""
    stale = {"path": "app/users.py", "line": None, "original_line": 13, "body": MARKER}
    github = FakeGitHub(existing=[stale])

    outcome = post_inline_comments(github, 1, pr(), HEAD, [finding()], 15)

    assert outcome.posted == 1


def test_a_human_comment_on_the_same_line_does_not_block_ours():
    human = {"path": "app/users.py", "line": 13, "body": "Can we rename this?"}

    assert existing_locations([human]) == set()


def test_two_findings_on_one_line_post_once():
    github = FakeGitHub()

    outcome = post_inline_comments(
        github, 1, pr(), HEAD, [finding(), finding(severity="nit", message="other")], 15
    )

    assert outcome.posted == 1
    assert outcome.duplicates == 1


def test_a_rejected_batch_falls_back_to_one_at_a_time():
    github = FakeGitHub(reject_batch=True, reject_paths={"app/gone.py"})

    outcome = post_inline_comments(
        github, 1, pr(), HEAD, [finding(), finding(path="app/gone.py", line=3)], 15
    )

    assert outcome.posted == 1
    assert outcome.failed == 1
    assert [c["path"] for c in github.singles] == ["app/users.py"]


def test_the_cap_keeps_the_first_findings():
    github = FakeGitHub()
    findings = [finding(line=n * 10) for n in range(1, 30)]

    outcome = post_inline_comments(github, 1, pr(), HEAD, findings, 5)

    assert outcome.posted == 5
    assert [c["line"] for c in github.reviews[0]["comments"]] == [10, 20, 30, 40, 50]


def test_no_head_sha_posts_nothing():
    github = FakeGitHub()

    assert post_inline_comments(github, 1, pr(), "", [finding()], 15).posted == 0
    assert github.reviews == []


# ======================================================== through the review flow


def completed(findings):
    return ReviewResult(findings=findings, succeeded=True, model_used="openai/gpt-oss-120b")


def agent_finding(line=11):
    return Finding(
        file="app/users.py",
        line=line,
        severity=Severity.BLOCKING,
        category="security",
        message="SQL built from input.",
        agent="security",
    )


@pytest.mark.django_db
def test_a_completed_review_posts_inline_comments_and_says_so(pull_request):  # noqa: F811
    with mock.patch("apps.reviews.services.post_inline_comments") as post:
        post.return_value = SimpleNamespace(posted=1, duplicates=0, failed=0)
        _, body = run(pull_request, completed([agent_finding()]))

    args = post.call_args.args
    assert args[3] == "abc1234def"
    assert [f.line for f in args[4]] == [11]
    assert "1 new inline comment" in body


@pytest.mark.django_db
def test_a_degraded_review_posts_no_inline_comments(pull_request):  # noqa: F811
    from apps.agents.types import AgentRun

    result = ReviewResult(
        findings=[],
        succeeded=False,
        failure_reason="groq: down",
        agent_runs=[AgentRun(name="static_analysis", succeeded=True)],
    )
    with mock.patch("apps.reviews.services.post_inline_comments") as post:
        run(pull_request, result)

    post.assert_not_called()


@pytest.mark.django_db
def test_an_inline_failure_never_loses_the_summary_comment(pull_request):  # noqa: F811
    with mock.patch(
        "apps.reviews.services.post_inline_comments", side_effect=GitHubAppError("boom")
    ):
        review, body = run(pull_request, completed([agent_finding()]))

    assert review.status == "done"
    assert "SQL built from input." in body
