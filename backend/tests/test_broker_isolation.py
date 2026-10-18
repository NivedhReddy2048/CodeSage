"""The suite must not be able to dispatch work to a real broker.

A guard is worthless if a later change can remove it without anything failing, and
this one protects against a failure that is invisible in CI: with Redis up and no
worker, a leaked `.delay()` just sits in a queue and every test still passes. The
cost lands on whoever runs the suite with their dev stack up (issue #49).
"""

import pytest

from apps.reviews.tasks import review_pull_request_task


def test_dispatch_is_intercepted_without_asking_for_the_fixture():
    """Autouse, so a new test file cannot opt out by forgetting it.

    Asserted through behaviour rather than by inspecting the patch: the sentinel id
    can only come from the fixture, and a real dispatch would return a live
    `AsyncResult` with a uuid.
    """
    result = review_pull_request_task.delay(1, 2)

    assert result.id == "test-task-id", (
        "a task dispatch returned a real result, so conftest is no longer "
        "intercepting and the suite can send messages to the broker"
    )


def test_delay_records_what_was_dispatched(never_reach_a_real_broker):
    """Recorded, so a test can still assert that work was queued."""
    review_pull_request_task.delay(7, 8)

    task = never_reach_a_real_broker.call_args.args[0]
    assert task.name == "reviews.review_pull_request"
    assert never_reach_a_real_broker.call_count == 1


def test_eager_execution_is_not_the_workaround():
    """Eager would run the review in-process, reaching GitHub and Groq for real.

    So the suite stays non-eager and relies on interception. This fails if someone
    reaches for `task_always_eager` as the fix.
    """
    from core.celery import app

    assert app.conf.task_always_eager is False


@pytest.mark.django_db
def test_calling_a_task_body_directly_still_works():
    """Interception covers dispatch, not the function.

    A missing pull request is the task's own early return, so reaching it proves the
    body ran rather than being swallowed by the patch.
    """
    assert review_pull_request_task(999_999, 1) is None
