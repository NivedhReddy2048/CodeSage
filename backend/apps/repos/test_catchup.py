"""The missed-webhook catch-up: what it reviews, what it leaves, and what it costs.

GitHub is mocked at github_app's two catch-up calls. Redis is real (the cache is
the point), and cleared per test.
"""

from unittest import mock

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.ingestion.models import IngestionJob
from apps.repos import catchup, tasks
from apps.repos.github_app import GitHubAppError
from apps.repos.models import WebhookEvent
from apps.reviews.models import Review
from tests import factories


@pytest.fixture(autouse=True)
def clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def repo(db):
    _owner, org = factories.user("alice")
    return factories.repository(org, "alice/app")


def pull(number, sha):
    return {
        "number": number,
        "id": 5000 + number,
        "title": f"Change {number}",
        "user": {"login": "bob"},
        "head": {"sha": sha},
        "base": {"ref": "main", "repo": {"name": "app", "owner": {"login": "alice"}}},
        "state": "open",
    }


@pytest.fixture
def github():
    """The two GitHub calls a run makes per repository, plus the ack comment."""
    with (
        mock.patch.object(catchup.github_app, "list_open_pull_requests") as pulls,
        mock.patch.object(catchup.github_app, "get_branch_head") as head,
        mock.patch.object(tasks.github_app, "create_issue_comment", return_value={"id": 77}),
    ):
        pulls.return_value = ([], 4000)
        head.return_value = ("", 4000)
        yield mock.Mock(pulls=pulls, head=head)


# ----------------------------------------------------------------- reviews


def test_an_unreviewed_head_is_reviewed_through_the_webhook_path(repo, github):
    github.pulls.return_value = ([pull(7, "a" * 40)], 4000)

    summary = catchup.catch_up()

    review = Review.objects.get()
    assert summary["queued"] == 1
    assert review.trigger == Review.Trigger.CATCHUP
    assert review.head_sha == "a" * 40
    assert review.pull_request.number == 7
    assert review.pull_request.ack_comment_id == 77
    event = WebhookEvent.objects.get()
    assert event.delivery_id.startswith("catchup:") and event.processed_at is not None


def test_a_head_that_already_has_a_review_is_left_alone(repo, github):
    pr = factories.pull_request(repo, number=3)
    factories.review(pr)  # reviewed at pr.head_sha, e.g. by a webhook that did arrive
    github.pulls.return_value = ([pull(3, pr.head_sha), pull(4, "b" * 40)], 4000)

    summary = catchup.catch_up()

    assert summary["already_reviewed"] == 1
    assert summary["queued"] == 1
    assert Review.objects.filter(head_sha="b" * 40).count() == 1


def test_the_same_head_is_never_queued_twice(repo, github):
    """Idempotent like webhooks: even with the cache gone, the delivery id collides."""
    github.pulls.return_value = ([pull(7, "a" * 40)], 4000)
    catchup.catch_up()
    cache.clear()
    Review.objects.all().delete()  # nothing for the database check to find either

    summary = catchup.catch_up()

    assert summary["queued"] == 0
    assert WebhookEvent.objects.count() == 1


def test_a_run_where_nothing_changed_never_touches_the_database(repo, github):
    """The Neon rule: GitHub first, Redis second, Postgres only for news."""
    pr = factories.pull_request(repo, number=3)
    factories.review(pr)
    github.pulls.return_value = ([pull(3, pr.head_sha)], 4000)
    catchup.catch_up()  # warms the repository list and learns the SHA is reviewed

    with CaptureQueriesContext(connection) as queries:
        summary = catchup.catch_up()

    assert len(queries) == 0, [q["sql"] for q in queries]
    assert summary["cached"] == 1


def test_a_webhook_review_is_remembered_so_the_catch_up_skips_the_database(repo, github):
    github.pulls.return_value = ([pull(7, "a" * 40)], 4000)
    catchup.connected_repositories()
    catchup.catch_up()  # queues the review, which marks the SHA

    with CaptureQueriesContext(connection) as queries:
        catchup.catch_up()

    assert len(queries) == 0


def test_no_open_pull_requests_means_no_review_query(repo, github):
    catchup.connected_repositories()

    with CaptureQueriesContext(connection) as queries:
        catchup.catch_up()

    assert len(queries) == 0


# --------------------------------------------------------------- rate limits


def test_a_low_rate_limit_stops_the_installation_after_that_repository(db, github):
    _owner, org = factories.user("carol")
    first = factories.repository(org, "carol/one")
    second = factories.repository(org, "carol/two")
    second.installation = first.installation
    second.save()
    github.pulls.return_value = ([], 50)
    github.head.return_value = ("", 50)

    summary = catchup.catch_up()

    assert summary["repositories"] == 1
    assert summary["rate_limited"] == 1
    assert github.pulls.call_count == 1


def test_a_github_error_skips_that_installation_but_not_the_others(db, github):
    _a, org_a = factories.user("dave")
    _b, org_b = factories.user("erin")
    factories.repository(org_a, "dave/app")
    factories.repository(org_b, "erin/app")
    github.pulls.side_effect = [GitHubAppError("403 rate limit exceeded"), ([], 4000)]

    summary = catchup.catch_up()

    assert summary["errors"] == 1
    assert summary["repositories"] == 1


def test_a_suspended_installation_is_not_visited(repo, github):
    repo.installation.suspended = True
    repo.installation.save()

    catchup.catch_up()

    github.pulls.assert_not_called()


def test_disconnecting_a_repository_drops_it_from_the_cached_list(repo, github):
    assert len(catchup.connected_repositories()) == 1

    repo.delete()

    assert catchup.connected_repositories() == []


def test_connecting_a_repository_adds_it_to_the_cached_list(repo, github):
    assert len(catchup.connected_repositories()) == 1

    factories.repository(repo.organization, "alice/second")

    assert len(catchup.connected_repositories()) == 2


def test_suspending_and_unsuspending_an_installation_updates_the_list(repo, github):
    assert len(catchup.connected_repositories()) == 1

    repo.installation.suspended = True
    repo.installation.save()
    assert catchup.connected_repositories() == []

    repo.installation.suspended = False
    repo.installation.save()
    assert len(catchup.connected_repositories()) == 1


# -------------------------------------------------------------------- index


def indexed(repo, sha):
    return IngestionJob.objects.create(
        repository=repo, status=IngestionJob.Status.DONE, commit_sha=sha
    )


def test_a_moved_default_branch_is_reindexed_once(repo, github):
    indexed(repo, "old" + "0" * 37)
    github.head.return_value = ("new" + "0" * 37, 4000)

    with mock.patch("apps.ingestion.services.start_ingestion", return_value=(None, True)) as start:
        first = catchup.catch_up()
        second = catchup.catch_up()

    assert first["reindexed"] == 1
    assert second["reindexed"] == 0
    start.assert_called_once()


def test_an_unmoved_branch_is_not_reindexed(repo, github):
    indexed(repo, "same" + "0" * 36)
    github.head.return_value = ("same" + "0" * 36, 4000)

    with mock.patch("apps.ingestion.services.start_ingestion") as start:
        catchup.catch_up()

    start.assert_not_called()


def test_a_repository_never_indexed_successfully_is_not_retried_here(repo, github):
    """Failing indexing every half hour would burn the embedding quota."""
    github.head.return_value = ("new" + "0" * 37, 4000)

    with mock.patch("apps.ingestion.services.start_ingestion") as start:
        catchup.catch_up()

    start.assert_not_called()


# --------------------------------------------------------------- scheduling


def test_scheduling_is_throttled_to_one_run_per_interval(never_reach_a_real_broker):
    assert catchup.schedule() is True
    assert catchup.schedule() is False
    assert catchup.schedule(force=True) is True  # worker startup always runs

    names = [call.args[0].name for call in never_reach_a_real_broker.call_args_list]
    assert names == ["repos.catch_up", "repos.catch_up"]


def test_the_health_ping_schedules_a_catch_up_without_the_database(never_reach_a_real_broker):
    """No django_db mark: a query here raises."""
    from django.test import Client

    Client().get("/api/health/")
    Client().get("/api/health/")

    assert never_reach_a_real_broker.call_count == 1


def test_a_broken_broker_does_not_fail_the_health_check(never_reach_a_real_broker):
    from django.test import Client

    never_reach_a_real_broker.side_effect = ConnectionError("broker down")

    assert Client().get("/api/health/").status_code == 200


def test_a_starting_worker_catches_up_at_once(never_reach_a_real_broker):
    from core.celery import catch_up_on_startup

    cache.set(catchup.DUE_KEY, "recent", timeout=600)  # a run was due-stamped already

    catch_up_on_startup()

    assert never_reach_a_real_broker.call_count == 1


def test_the_task_runs_a_pass(repo, github):
    assert tasks.catch_up_task() == {"repositories": 1}
