"""Phase 6a review endpoints: list, status, re-run, and error-detail visibility."""

import pytest

from apps.accounts.models import Membership
from apps.audit.models import AuditLogEntry
from apps.reviews.models import Review
from tests import factories

RAW = 'groq: HTTP 429: {"error": "Rate limit reached in organization org_01abc, Used 199812"}'


@pytest.fixture
def world(db):
    alice, org_a = factories.user("alice")
    bob, org_b = factories.user("bob")
    repo_a = factories.repository(org_a, "alice/app")
    repo_b = factories.repository(org_b, "bob/app")
    pr_a = factories.pull_request(repo_a, 1, "Paginate")
    pr_b = factories.pull_request(repo_b, 1, "Bob's change")
    done_a = factories.review(
        pr_a,
        findings=[("blocking", "security", "security"), ("nit", "style", "test_coverage")],
    )
    degraded_a = factories.review(pr_a, Review.Status.FAILED, degraded=True, findings=(), error=RAW)
    review_b = factories.review(pr_b, findings=[("blocking", "security", "security")])
    return locals()


# ---------------------------------------------------------------------- list


def test_the_list_shows_only_my_organisations_reviews(world):
    response = factories.client(world["alice"]).get("/api/reviews/")

    assert response.status_code == 200
    ids = {row["id"] for row in response.data["results"]}
    assert ids == {world["done_a"].pk, world["degraded_a"].pk}
    assert world["review_b"].pk not in ids


def test_the_list_counts_findings_by_severity(world):
    rows = factories.client(world["alice"]).get("/api/reviews/").data["results"]
    done = next(r for r in rows if r["id"] == world["done_a"].pk)

    assert (done["finding_count"], done["blocking_count"], done["nit_count"]) == (2, 1, 1)
    assert done["repository"] == "alice/app"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("status=done", {"done_a"}),
        ("status=degraded", {"degraded_a"}),
        ("severity=blocking", {"done_a"}),
        ("severity=nit", {"done_a"}),
    ],
)
def test_the_list_filters(world, query, expected):
    rows = factories.client(world["alice"]).get(f"/api/reviews/?{query}").data["results"]

    assert {r["id"] for r in rows} == {world[name].pk for name in expected}


def test_filtering_by_another_organisations_repository_returns_nothing(world):
    repo_b = world["repo_b"].pk
    rows = factories.client(world["alice"]).get(f"/api/reviews/?repository={repo_b}").data

    assert rows["results"] == []


# -------------------------------------------------------------------- status


def test_status_returns_the_progress_snapshot(world):
    review = world["done_a"]
    Review.objects.filter(pk=review.pk).update(progress={"security": "ok", "grounding": "running"})

    data = factories.client(world["alice"]).get(f"/api/reviews/{review.pk}/status/").data

    assert data["agents"]["security"] == "ok"
    assert data["agents"]["diff_intent"] == "pending"
    assert (data["completed"], data["total"]) == (1, 5)


def test_status_of_another_organisations_review_is_not_found(world):
    response = factories.client(world["alice"]).get(f"/api/reviews/{world['review_b'].pk}/status/")

    assert response.status_code == 404


# ------------------------------------------------------- raw error visibility


def test_a_member_sees_the_short_reason_never_the_raw_error(world):
    member, _ = factories.user("carol")
    org_a = world["repo_a"].organization
    factories.add_member(member, org_a, Membership.Role.MEMBER)

    data = factories.client(member, org_a).get(f"/api/reviews/{world['degraded_a'].pk}/").data

    assert data["error"] == ""
    assert data["error_summary"] == "AI providers unavailable"
    assert data["can_manage"] is False
    assert "org_01abc" not in str(data)


def test_an_owner_sees_the_raw_error(world):
    data = factories.client(world["alice"]).get(f"/api/reviews/{world['degraded_a'].pk}/").data

    assert data["error"] == RAW
    assert data["error_summary"] == "AI providers unavailable"
    assert data["can_manage"] is True
    assert data["pr_url"] == "https://github.com/alice/app/pull/1"


def test_agent_run_errors_follow_the_same_rule(world):
    factories.agent_run(world["degraded_a"], "security", error=RAW, requested_model="m")
    member, _ = factories.user("dave")
    org_a = world["repo_a"].organization
    factories.add_member(member, org_a, Membership.Role.MEMBER)

    as_member = factories.client(member, org_a).get(f"/api/reviews/{world['degraded_a'].pk}/")
    as_owner = factories.client(world["alice"]).get(f"/api/reviews/{world['degraded_a'].pk}/")

    assert as_member.data["agent_runs"][0]["error"] == ""
    assert as_member.data["agent_runs"][0]["error_summary"] == "AI providers unavailable"
    assert as_owner.data["agent_runs"][0]["error"] == RAW


# -------------------------------------------------------------------- re-run


PR_DATA = {"id": 1, "title": "Paginate", "head": {"sha": "fffffff"}, "base": {"ref": "main"}}


def test_an_owner_can_rerun_and_it_is_queued_and_audited(world, never_reach_a_real_broker):
    from unittest import mock

    with mock.patch("apps.reviews.rerun.github_app.get_pull_request", return_value=PR_DATA):
        response = factories.client(world["alice"]).post(
            f"/api/reviews/{world['done_a'].pk}/rerun/"
        )

    assert response.status_code == 202
    fresh = Review.objects.get(pk=response.data["review_id"])
    assert fresh.status == Review.Status.PENDING
    assert fresh.head_sha == "fffffff"

    task, args = (
        never_reach_a_real_broker.call_args.args[0],
        never_reach_a_real_broker.call_args.args[1],
    )
    assert task.name == "reviews.review_pull_request"
    assert args[2] == fresh.pk

    entry = AuditLogEntry.objects.get(action="review.rerun")
    assert entry.organization == world["repo_a"].organization
    assert entry.actor == world["alice"]
    assert entry.metadata["new_review"] == fresh.pk


def test_a_member_cannot_rerun(world):
    member, _ = factories.user("erin")
    org_a = world["repo_a"].organization
    factories.add_member(member, org_a, Membership.Role.MEMBER)

    response = factories.client(member, org_a).post(f"/api/reviews/{world['done_a'].pk}/rerun/")

    assert response.status_code == 403
    assert not AuditLogEntry.objects.exists()


def test_rerunning_another_organisations_review_is_not_found(world):
    response = factories.client(world["alice"]).post(f"/api/reviews/{world['review_b'].pk}/rerun/")

    assert response.status_code == 404
    assert Review.objects.filter(pull_request=world["pr_b"]).count() == 1


def test_a_rerun_while_one_is_in_progress_is_refused(world):
    factories.review(world["pr_a"], Review.Status.RUNNING)

    response = factories.client(world["alice"]).post(f"/api/reviews/{world['done_a'].pk}/rerun/")

    assert response.status_code == 409
    assert "already in progress" in response.data["detail"]


def test_a_stale_running_review_does_not_block_a_rerun(world):
    from unittest import mock

    factories.review(world["pr_a"], Review.Status.RUNNING, days_ago=1)

    with mock.patch("apps.reviews.rerun.github_app.get_pull_request", return_value=PR_DATA):
        response = factories.client(world["alice"]).post(
            f"/api/reviews/{world['done_a'].pk}/rerun/"
        )

    assert response.status_code == 202


# --------------------------------------------- a review always ends, and notifies


def test_a_crashing_review_is_marked_failed_never_left_running(world):
    from unittest import mock

    from apps.notifications.models import Notification
    from apps.reviews import services

    pending = factories.review(world["pr_a"], Review.Status.PENDING)
    with (
        mock.patch("apps.reviews.services.github_app"),
        mock.patch("apps.reviews.services.fetch_diff", return_value="diff"),
        mock.patch("apps.reviews.services.run_pipeline", side_effect=RuntimeError("boom")),
    ):
        review = services.review_pull_request(world["pr_a"], 1, review=pending)

    assert review.pk == pending.pk
    assert review.status == Review.Status.FAILED
    assert "boom" in review.error
    note = Notification.objects.get(recipient=world["alice"])
    assert note.kind == "review.failed"
    assert note.link == f"/reviews/{review.pk}"


def test_progress_survives_the_end_of_the_review(world):
    """Found live: the final full save of the Review overwrote the reporter's progress,
    so the finished event and the status endpoint both said 0/5."""
    from unittest import mock

    from apps.agents.graph import AGENT_NAMES
    from apps.agents.types import ReviewResult
    from apps.reviews import services

    def pipeline(diff, context, config, retrieve=None, on_progress=None):
        for name in AGENT_NAMES:
            on_progress(name, "started", "")
            on_progress(name, "finished", "ok")
        return ReviewResult(succeeded=True, model_used="m")

    pending = factories.review(world["pr_a"], Review.Status.PENDING)
    with (
        mock.patch("apps.reviews.services.github_app"),
        mock.patch("apps.reviews.services.fetch_diff", return_value="diff"),
        mock.patch("apps.reviews.services.run_pipeline", side_effect=pipeline),
        mock.patch("apps.reviews.progress.broadcast") as broadcast,
    ):
        services.review_pull_request(world["pr_a"], 1, review=pending)

    pending.refresh_from_db()
    assert pending.progress == {name: "ok" for name in AGENT_NAMES}
    finished = broadcast.call_args.args[1]
    assert finished["type"] == "review.finished"
    assert finished["completed"] == 5
