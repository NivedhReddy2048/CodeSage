"""Suite-wide safety rails.

`pytest-django` isolates the database into `test_<name>`. Nothing isolates the
broker: `CELERY_BROKER_URL` under test is the same Redis a developer's worker is
listening to, and `CELERY_TASK_ALWAYS_EAGER` is false, so a `.delay()` reached
during a test is a real message onto a real queue. A worker running alongside the
suite then executes it with the *development* settings, database and credentials.

That is not hypothetical. It was found by watching the worker log during the phase 5
live tests (issue #49): four full six-agent reviews, nine seconds each, running live
model calls and editing comments on a real pull request, every time the suite ran.
No test calls `.delay()` itself - the webhook handler does, and most of the handler
tests exercise it for real, so the only reason they looked harmless is that CI
starts Redis without a worker and the messages pile up unread.

Eagerness is not the fix. It would run the review inside the test process instead,
which still reaches GitHub and Groq. Dispatch is recorded and dropped.
"""

from unittest import mock

import pytest
from celery.app.task import Task


@pytest.fixture(autouse=True)
def never_reach_a_real_broker():
    """Record every task dispatch; send none of it anywhere.

    `delay` and `apply_async` both end at `Task.apply_async`, so patching that one
    method covers every call site, including the ones inside application code that a
    test never sees. Calling a task function directly is untouched, which is how the
    task tests still exercise their bodies.
    """
    with mock.patch.object(Task, "apply_async", autospec=True) as apply_async:
        apply_async.return_value = mock.Mock(id="test-task-id")
        yield apply_async


@pytest.fixture(autouse=True)
def in_memory_channel_layer(settings):
    """Live progress events go to an in-process layer, never the developer's Redis.

    Channels drops its cached layer when CHANNEL_LAYERS changes, so each test gets a
    fresh, empty one.
    """
    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    yield
