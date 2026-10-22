"""Earlier inline comments whose verdict no longer stands are marked superseded.

Seen on testbed PRs #5 and #7: after the anchoring and severity fixes, the old
"Blocking" comments at #5 :6 and #7 :4 / :15 stayed on the diff beside the corrected
nits. The summary comment is edited in place; inline comments only accumulated.
"""

from types import SimpleNamespace

from apps.repos.github_app import GitHubAppError
from apps.reviews import comment
from apps.reviews.inline import (
    MARKER,
    SUPERSEDED_MARKER,
    comment_severity,
    post_inline_comments,
    render_comment,
)

HEAD = "e30facc9999"
PATH = "app/reports.py"


def finding(line, severity="nit", message="No test covers it.", placement="inline"):
    return SimpleNamespace(
        file_path=PATH,
        line=line,
        severity=severity,
        category="testing",
        message=message,
        agent="test_coverage",
        placement=placement,
    )


def posted(comment_id, line, severity="blocking", message="Old verdict.", path=PATH):
    return {
        "id": comment_id,
        "path": path,
        "line": line,
        "body": render_comment(finding(line, severity, message)),
    }


class GitHub:
    """Mocked GitHub: review comments over REST, threads over GraphQL."""

    def __init__(self, comments=(), refuse_resolve=False):
        self.comments = [dict(c) for c in comments]
        self.edits, self.resolved, self.reviews = [], [], []
        self.refuse_resolve = refuse_resolve
        self.deleted = []  # nothing may ever land here

    def list_review_comments(self, installation_id, repo, number):
        return [dict(c) for c in self.comments]

    def update_review_comment(self, installation_id, repo, comment_id, body):
        self.edits.append((comment_id, body))
        for c in self.comments:
            if c["id"] == comment_id:
                c["body"] = body
        return {"id": comment_id}

    def list_review_threads(self, installation_id, repo, number):
        return {c["id"]: (f"thread-{c['id']}", False) for c in self.comments}

    def resolve_review_thread(self, installation_id, thread_id):
        if self.refuse_resolve:
            raise GitHubAppError("GraphQL error: Resource not accessible by integration")
        self.resolved.append(thread_id)

    def create_review(self, installation_id, repo, number, commit_id, body, comments):
        self.reviews.append(comments)
        return {"id": 1}

    def delete_review_comment(self, *args):  # pragma: no cover - must never be called
        self.deleted.append(args)


def pr():
    return SimpleNamespace(number=7, repository=SimpleNamespace(full_name="o/testbed"))


def run(github, findings):
    return post_inline_comments(github, 1, pr(), HEAD, findings, 15)


# ------------------------------------------------------------ the testbed case


def test_pr7_the_old_blocking_comments_are_superseded_and_resolved():
    """#7: Blocking at :4 and :15 from the old run; this run has nits at :3 and :17."""
    github = GitHub([posted(41, 4), posted(42, 15)])

    outcome = run(github, [finding(3), finding(17)])

    assert (outcome.superseded, outcome.resolved, outcome.posted) == (2, 2, 2)
    assert github.resolved == ["thread-41", "thread-42"]
    for _comment_id, body in github.edits:
        assert body.startswith("Superseded by review of `e30facc`.")
        assert "~~**Blocking · testing** — Old verdict.~~" in body
        # Still ours, and recognisably done, so it is never edited twice.
        assert MARKER in body and SUPERSEDED_MARKER in body
    assert [c["line"] for c in github.reviews[0]] == [3, 17]
    assert github.deleted == []


def test_a_changed_severity_supersedes_and_the_new_verdict_is_posted():
    """Same line, Blocking before, nit now: the nit is not a 'duplicate'."""
    github = GitHub([posted(50, 3, "blocking")])

    outcome = run(github, [finding(3, "nit")])

    assert outcome.superseded == 1
    assert (outcome.posted, outcome.duplicates) == (1, 0)
    assert github.reviews[0][0]["body"].startswith("**Nit")


def test_an_unchanged_verdict_is_left_alone():
    github = GitHub([posted(60, 3, "nit")])

    outcome = run(github, [finding(3, "nit")])

    assert (outcome.superseded, outcome.duplicates, outcome.posted) == (0, 1, 0)
    assert github.edits == []


# ---------------------------------------------------------------- edge cases


def test_a_superseded_comment_is_never_edited_again():
    github = GitHub([posted(70, 6)])
    run(github, [])
    first = list(github.edits)

    run(github, [])

    assert github.edits == first


def test_an_outdated_comment_is_superseded():
    """GitHub nulls `line` once the code under a comment changed."""
    github = GitHub([posted(80, None) | {"original_line": 6}])

    assert run(github, [finding(6, "blocking")]).superseded == 1


def test_a_clean_rereview_still_supersedes():
    github = GitHub([posted(90, 6)])

    outcome = run(github, [])

    assert outcome.superseded == 1


def test_when_github_refuses_to_resolve_the_comment_is_only_edited():
    github = GitHub([posted(1, 4), posted(2, 15)], refuse_resolve=True)

    outcome = run(github, [])

    assert (outcome.superseded, outcome.resolved) == (2, 0)
    assert len(github.edits) == 2


def test_other_peoples_comments_are_never_touched():
    human = {"id": 5, "path": PATH, "line": 4, "body": "**Blocking** I disagree with this."}
    github = GitHub([human])

    run(github, [])

    assert github.edits == []


def test_a_failed_edit_costs_that_comment_only():
    class Flaky(GitHub):
        def update_review_comment(self, installation_id, repo, comment_id, body):
            if comment_id == 1:
                raise GitHubAppError("404")
            return super().update_review_comment(installation_id, repo, comment_id, body)

    github = Flaky([posted(1, 4), posted(2, 15)])

    outcome = run(github, [])

    assert outcome.superseded == 1
    assert [cid for cid, _ in github.edits] == [2]


def test_the_label_is_read_back_from_the_comment():
    assert comment_severity(render_comment(finding(1, "blocking"))) == "blocking"
    assert comment_severity(render_comment(finding(1, "nit"))) == "nit"
    assert comment_severity("Superseded by review of `x`.") == ""


def test_the_summary_says_how_many_were_superseded():
    from apps.reviews.inline import InlineOutcome

    note = comment._render_inline_note(InlineOutcome(posted=2, superseded=3))

    assert (
        note
        == "_Inline on the changed lines: 2 new inline comments, 3 earlier comments superseded._"
    )
