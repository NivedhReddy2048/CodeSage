"""The /ws/reviews/<id>/ progress socket and the progress it streams.

transaction=True for the socket tests: the consumer reads the database from a
worker thread, which cannot see rows inside a per-test transaction that has not
committed.
"""

from unittest import mock

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator

from apps.accounts.models import Membership
from apps.reviews import consumers, progress
from apps.reviews.models import Review
from core.asgi import application
from tests import factories

ORIGIN = [(b"origin", b"http://localhost:3000")]


def socket(review_id):
    return WebsocketCommunicator(application, f"/ws/reviews/{review_id}/", headers=ORIGIN)


async def authenticated(review_id, token):
    communicator = socket(review_id)
    connected, _ = await communicator.connect()
    assert connected
    await communicator.send_json_to({"type": "auth", "token": token})
    return communicator


@pytest.fixture
def tenants(db):
    alice, org_a = factories.user("alice")
    bob, org_b = factories.user("bob")
    review_a = factories.review(factories.pull_request(factories.repository(org_a)))
    review_b = factories.review(factories.pull_request(factories.repository(org_b)))
    return alice, bob, review_a, review_b


@pytest.mark.django_db(transaction=True)
def test_an_authenticated_member_gets_the_snapshot_then_live_events(tenants):
    alice, _, review_a, _ = tenants

    async def scenario():
        communicator = await authenticated(review_a.pk, factories.access_token(alice))
        first = await communicator.receive_json_from()
        assert first["type"] == "review.snapshot"
        assert first["review_id"] == review_a.pk
        assert (first["completed"], first["total"]) == (0, 6)

        reporter = await sync_to_async(progress.ProgressReporter)(review_a)
        await sync_to_async(reporter)("security", "started")
        started = await communicator.receive_json_from()
        await sync_to_async(reporter)("security", "finished", "ok")
        await sync_to_async(reporter)("static_analysis", "finished", "skipped")
        await communicator.receive_json_from()
        latest = await communicator.receive_json_from()
        await communicator.disconnect()
        return started, latest

    started, latest = async_to_sync(scenario)()

    assert started["type"] == "review.progress"
    assert (started["agent"], started["state"]) == ("security", "running")
    assert latest["completed"] == 2
    assert latest["agents"]["security"] == "ok"
    assert latest["agents"]["static_analysis"] == "skipped"
    # Persisted too, for the poll fallback and late joiners.
    assert Review.objects.get(pk=review_a.pk).progress["security"] == "ok"


@pytest.mark.django_db(transaction=True)
def test_another_organisations_review_closes_as_not_found(tenants):
    _, bob, review_a, _ = tenants

    async def scenario():
        communicator = await authenticated(review_a.pk, factories.access_token(bob))
        message = await communicator.receive_output()
        await communicator.wait()
        return message

    message = async_to_sync(scenario)()

    assert message == {"type": "websocket.close", "code": consumers.CLOSE_NOT_FOUND}


@pytest.mark.django_db(transaction=True)
def test_a_user_never_receives_events_for_another_organisations_review(tenants):
    """Bob watches his own review while Alice's is running: he hears nothing of it."""
    alice, bob, review_a, review_b = tenants

    async def scenario():
        bobs = await authenticated(review_b.pk, factories.access_token(bob))
        await bobs.receive_json_from()  # his own snapshot

        reporter = await sync_to_async(progress.ProgressReporter)(review_a)
        await sync_to_async(reporter)("security", "started")
        await sync_to_async(progress.announce_finished)(review_a)

        heard = await bobs.receive_nothing(timeout=0.3)
        await bobs.disconnect()
        return heard

    assert async_to_sync(scenario)() is True


@pytest.mark.django_db(transaction=True)
def test_a_member_of_a_second_organisation_may_watch_its_reviews(tenants):
    alice, bob, review_a, _ = tenants
    factories.add_member(bob, review_a.pull_request.repository.organization, Membership.Role.MEMBER)

    async def scenario():
        communicator = await authenticated(review_a.pk, factories.access_token(bob))
        message = await communicator.receive_json_from()
        await communicator.disconnect()
        return message

    assert async_to_sync(scenario)()["type"] == "review.snapshot"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "first_message",
    [
        {"type": "auth", "token": "not-a-jwt"},
        {"type": "auth"},
        {"type": "subscribe", "review": 1},
        ["auth"],
    ],
)
def test_a_bad_or_missing_token_closes_as_unauthenticated(tenants, first_message):
    _, _, review_a, _ = tenants

    async def scenario():
        communicator = socket(review_a.pk)
        await communicator.connect()
        await communicator.send_json_to(first_message)
        message = await communicator.receive_output()
        await communicator.wait()
        return message

    message = async_to_sync(scenario)()

    assert message == {"type": "websocket.close", "code": consumers.CLOSE_UNAUTHENTICATED}


@pytest.mark.django_db(transaction=True)
def test_an_expired_token_closes_as_unauthenticated(tenants, settings):
    from datetime import timedelta

    from rest_framework_simplejwt.tokens import AccessToken

    alice, _, review_a, _ = tenants
    token = AccessToken.for_user(alice)
    token.set_exp(lifetime=-timedelta(minutes=1))

    async def scenario():
        communicator = await authenticated(review_a.pk, str(token))
        message = await communicator.receive_output()
        await communicator.wait()
        return message

    assert async_to_sync(scenario)()["code"] == consumers.CLOSE_UNAUTHENTICATED


@pytest.mark.django_db(transaction=True)
def test_a_socket_that_never_authenticates_is_closed(tenants):
    _, _, review_a, _ = tenants

    async def scenario():
        with mock.patch.object(consumers, "AUTH_TIMEOUT", 0.05):
            communicator = socket(review_a.pk)
            await communicator.connect()
            message = await communicator.receive_output(timeout=1)
            await communicator.wait()
            return message

    assert async_to_sync(scenario)()["code"] == consumers.CLOSE_UNAUTHENTICATED


@pytest.mark.django_db(transaction=True)
def test_the_finished_event_carries_the_final_status(tenants):
    alice, _, review_a, _ = tenants

    async def scenario():
        communicator = await authenticated(review_a.pk, factories.access_token(alice))
        await communicator.receive_json_from()
        await sync_to_async(progress.announce_finished)(review_a)
        message = await communicator.receive_json_from()
        await communicator.disconnect()
        return message

    message = async_to_sync(scenario)()
    assert message["type"] == "review.finished"
    assert message["status"] == "done"


# ----------------------------------------------------------- the pipeline's side


def test_the_pipeline_reports_every_agent_starting_and_finishing():
    """Through the real graph, with providers mocked: 6 agents, each started then finished."""
    from apps.agents.graph import Runtime, run_pipeline
    from apps.agents.providers import ProviderResponse
    from apps.agents.static_analysis import AnalysisReport
    from apps.agents.types import RepoContext, ReviewConfig

    diff = (
        "diff --git a/app/x.py b/app/x.py\n--- a/app/x.py\n+++ b/app/x.py\n"
        "@@ -1,1 +1,2 @@\n x = 1\n+y = 2\n"
    )
    events = []

    def complete(self, model, system_prompt, user_message, schema=None):
        if "classify" in system_prompt:
            return ProviderResponse('{"intent": "fix", "summary": "s"}', 10, 5), "groq", False
        return ProviderResponse('{"findings": []}', 10, 5), "groq", False

    with (
        mock.patch.object(Runtime, "complete", complete),
        mock.patch("apps.agents.nodes.run_analysis", return_value=AnalysisReport(ran=["ruff"])),
    ):
        run_pipeline(
            diff,
            RepoContext(full_name="o/r", pr_number=1),
            ReviewConfig(groq_api_key="k"),
            on_progress=lambda agent, state, status: events.append((agent, state, status)),
        )

    agents = {
        "diff_intent",
        "static_analysis",
        "security",
        "correctness",
        "grounding",
        "test_coverage",
    }
    assert {a for a, state, _ in events if state == "started"} == agents
    finished = {a: status for a, state, status in events if state == "finished"}
    assert set(finished) == agents
    assert finished["grounding"] == "skipped"  # no retrieval configured
    assert finished["security"] == "ok"
    assert finished["correctness"] == "ok"
    # diff_intent runs alone, before the fan-out.
    assert events[0] == ("diff_intent", "started", "")


def test_a_failing_progress_callback_never_fails_the_review():
    from apps.agents.graph import Runtime
    from apps.agents.types import ReviewConfig

    def explode(*args):
        raise RuntimeError("socket gone")

    Runtime(ReviewConfig(), on_progress=explode).report("security", "started")


@pytest.mark.django_db
def test_broadcast_reaches_the_review_group():
    layer = get_channel_layer()
    channel = async_to_sync(layer.new_channel)()
    async_to_sync(layer.group_add)(progress.group_name(7), channel)

    progress.broadcast(7, {"type": "review.progress", "agent": "security"})

    message = async_to_sync(layer.receive)(channel)
    assert message == {
        "type": "review.event",
        "event": {"type": "review.progress", "agent": "security"},
    }
