"""The free demo's daily review caps: who they stop, what the PR is told, and how
the PR still gets its review after the reset."""

import threading
from datetime import timedelta
from unittest import mock

import pytest
from django.core.cache import cache
from django.db import connections
from django.urls import reverse
from django.utils import timezone

from apps.repos import catchup, tasks
from apps.repos.models import WebhookEvent
from apps.reviews import quota
from apps.reviews.models import Review
from tests import factories


@pytest.fixture(autouse=True)
def caps(settings):
    settings.DEMO_REVIEWS_PER_WORKSPACE_PER_DAY = 2
    settings.DEMO_REVIEWS_PER_DAY = 3
    cache.clear()
    yield settings
    cache.clear()


@pytest.fixture
def world(db):
    alice, org = factories.user("alice")
    repo = factories.repository(org, "alice/app")
    return alice, org, repo


def spend(repo, count, when=None):
    """`count` reviews in `repo`'s workspace, created today unless `when` says not."""
    for number in range(count):
        pr = factories.pull_request(repo, number=100 + number + Review.objects.count())
        review = factories.review(pr)
        if when is not None:
            Review.objects.filter(pk=review.pk).update(created_at=when)


def deliver(repo, number=7, sha="c" * 40, delivery="d-1"):
    """Run one pull_request webhook for `repo` through the real handler."""
    body = {
        "action": "opened",
        "installation": {"id": repo.installation.installation_id},
        "repository": {
            "id": repo.github_id,
            "full_name": repo.full_name,
            "name": repo.name,
            "owner": {"login": repo.owner},
            "default_branch": "main",
            "private": False,
        },
        "pull_request": {
            "number": number,
            "id": 9000 + number,
            "title": "Change",
            "user": {"login": "bob"},
            "head": {"sha": sha},
            "base": {"ref": "main"},
            "state": "open",
        },
    }
    event = WebhookEvent.objects.create(
        delivery_id=delivery, event="pull_request", action="opened", payload=body
    )
    tasks.handle_webhook_event(event.pk)


# ---------------------------------------------------------------- webhooks


def test_a_review_under_the_cap_starts(world, never_reach_a_real_broker):
    _alice, _org, repo = world
    with mock.patch.object(tasks.github_app, "create_issue_comment", return_value={"id": 5}):
        deliver(repo)

    assert Review.objects.filter(head_sha="c" * 40).count() == 1
    assert never_reach_a_real_broker.call_count == 1


def test_the_workspace_cap_refuses_with_one_clear_comment(world, never_reach_a_real_broker):
    _alice, _org, repo = world
    spend(repo, 2)

    with mock.patch.object(
        tasks.github_app, "create_issue_comment", return_value={"id": 5}
    ) as post:
        deliver(repo)

    assert not Review.objects.filter(head_sha="c" * 40).exists()
    never_reach_a_real_broker.assert_not_called()
    body = post.call_args.args[3]
    assert body.startswith(
        "**Daily free-demo limit reached; this PR will be reviewed after the limit resets.**"
    )
    assert "This workspace has used its 2 free reviews for today." in body
    assert "05:30 IST" in body


def test_a_second_push_while_capped_edits_the_same_comment(world):
    _alice, _org, repo = world
    spend(repo, 2)
    with mock.patch.object(tasks.github_app, "create_issue_comment", return_value={"id": 5}):
        deliver(repo, sha="c" * 40, delivery="d-1")

    with (
        mock.patch.object(tasks.github_app, "create_issue_comment") as post,
        mock.patch.object(tasks.github_app, "update_issue_comment") as edit,
    ):
        deliver(repo, sha="d" * 40, delivery="d-2")

    post.assert_not_called()
    assert edit.call_args.args[2] == 5


def test_the_global_cap_refuses_every_workspace(world):
    _alice, _org, repo = world
    _bob, other_org = factories.user("bob")
    spend(factories.repository(other_org, "bob/app"), 2)
    spend(repo, 1)  # alice is under her own cap, but 3 of 3 are used overall

    refused = quota.denial(repo.organization)

    assert refused.scope == "global"
    assert "shared limit of 3" in refused.message


def test_yesterdays_reviews_do_not_count(world):
    _alice, org, repo = world
    spend(repo, 2, when=timezone.now() - timedelta(days=1, hours=1))

    assert quota.denial(org) is None


def test_the_day_turns_over_at_utc_midnight():
    noon = timezone.datetime(2026, 11, 2, 12, 0, tzinfo=timezone.UTC)

    assert quota.resets_at(noon).isoformat() == "2026-11-03T00:00:00+00:00"
    assert quota.seconds_until_reset(noon) == 12 * 60 * 60


@pytest.mark.django_db(transaction=True)
def test_concurrent_admissions_cannot_both_take_the_last_slot(caps):
    """Two webhooks at once, one slot left: the lock makes the second see 2 of 2."""
    caps.DEMO_REVIEWS_PER_WORKSPACE_PER_DAY = 1
    _alice, org = factories.user("alice")
    pr = factories.pull_request(factories.repository(org, "alice/app"))
    outcomes, start = [], threading.Barrier(2)

    def admit():
        try:
            start.wait()
            with quota.admission(org) as refused:
                if refused is None:
                    Review.objects.create(pull_request=pr, head_sha="e" * 40)
                    threading.Event().wait(0.2)  # hold the lock while the other waits
                outcomes.append(refused is None)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=admit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == [False, True]
    assert Review.objects.count() == 1


# ------------------------------------------------------------------ catch-up


def test_the_catch_up_defers_while_capped_and_reviews_after_the_reset(world):
    _alice, _org, repo = world
    spend(repo, 2)
    pull = {
        "number": 7,
        "head": {"sha": "f" * 40},
        "base": {"ref": "main", "repo": {}},
        "title": "Late",
        "user": {"login": "bob"},
    }
    with (
        mock.patch.object(
            catchup.github_app, "list_open_pull_requests", return_value=([pull], 4000)
        ),
        mock.patch.object(catchup.github_app, "get_branch_head", return_value=("", 4000)),
        mock.patch.object(tasks.github_app, "create_issue_comment", return_value={"id": 5}),
    ):
        capped = catchup.catch_up()
        assert capped["deferred"] == 1
        assert not WebhookEvent.objects.exists()  # nothing filed only to be refused

        again = catchup.catch_up()  # still capped: answered from Redis
        assert again["cached"] == 1

        # Midnight UTC: yesterday's reviews stop counting, the deferral expires.
        Review.objects.update(created_at=timezone.now() - timedelta(days=1))
        cache.delete(catchup._deferred_key(repo.pk, "f" * 40))
        after = catchup.catch_up()

    assert after["queued"] == 1
    assert Review.objects.get(head_sha="f" * 40).trigger == Review.Trigger.CATCHUP


# -------------------------------------------------------------------- re-run


def test_a_rerun_over_the_cap_is_refused_with_429(world):
    alice, org, repo = world
    spend(repo, 2)
    review = Review.objects.first()

    with mock.patch(
        "apps.reviews.rerun.github_app.get_pull_request",
        return_value={"id": 1, "head": {"sha": "a" * 40}, "base": {"ref": "main"}},
    ):
        response = factories.client(alice).post(reverse("review-rerun", args=[review.pk]))

    assert response.status_code == 429
    assert response.json()["detail"].startswith("Daily free-demo limit reached.")
    assert Review.objects.count() == 2


# ------------------------------------------------------------------ the API


def test_the_demo_endpoint_reports_usage_and_limits(world):
    alice, _org, repo = world
    spend(repo, 2)

    body = factories.client(alice).get(reverse("demo-limits")).json()

    assert body["reviews"]["workspace"] == {"used": 2, "limit": 2}
    assert body["reviews"]["global"] == {"used": 2, "limit": 3}
    assert body["reviews"]["limited"] is True
    assert body["reviews"]["scope"] == "workspace"
    assert body["reviews"]["resets_at"].endswith("T00:00:00Z")
    assert body["repositories"] == {"used": 1, "limit": 3}
    assert body["max_chunks_per_repo"] == 2000
    assert body["public_only"] is True


def test_the_demo_endpoint_requires_sign_in(db):
    from rest_framework.test import APIClient

    assert APIClient().get(reverse("demo-limits")).status_code == 401
