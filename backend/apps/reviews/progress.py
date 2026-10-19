"""Live review progress: persisted on the Review, broadcast over Channels.

The pipeline runs in the Celery worker; browsers are connected to the web process.
The Redis channel layer joins them: the worker `group_send`s to `review-<id>`, and
every consumer subscribed to that group forwards the event to its socket.

State is also written to `Review.progress` on every event, so the poll fallback and
a socket that connects halfway through both start from the truth rather than from
whatever events they happened to catch.
"""

import logging
import threading

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from apps.agents.graph import AGENT_NAMES

logger = logging.getLogger(__name__)

TOTAL_AGENTS = len(AGENT_NAMES)
DONE_STATES = frozenset({"ok", "failed", "skipped"})


def group_name(review_id):
    return f"review-{review_id}"


def initial_progress():
    return {name: "pending" for name in AGENT_NAMES}


def snapshot(review):
    """The full current state, in the same shape the socket's first message has."""
    agents = {**initial_progress(), **(review.progress or {})}
    return {
        "type": "review.snapshot",
        "review_id": review.pk,
        "status": review.status,
        "degraded": review.degraded,
        "agents": agents,
        "completed": sum(1 for state in agents.values() if state in DONE_STATES),
        "total": TOTAL_AGENTS,
    }


def broadcast(review_id, event):
    """Send one event to everyone watching this review. Never raises."""
    try:
        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)(
            group_name(review_id), {"type": "review.event", "event": event}
        )
    except Exception:  # noqa: BLE001 - a dropped live update must not fail the review
        logger.exception("Could not broadcast %s for review %s", event.get("type"), review_id)


class ProgressReporter:
    """The `on_progress` callback handed to the pipeline for one review.

    The four analysis agents run on parallel threads and report at the same time,
    so the read-modify-write of the state is under a lock.
    """

    def __init__(self, review):
        self.review = review
        self.agents = initial_progress()
        self.lock = threading.Lock()
        self._save()

    def __call__(self, agent, state, status=""):
        with self.lock:
            self.agents[agent] = "running" if state == "started" else (status or "ok")
            agents = dict(self.agents)
            self._save()

        completed = sum(1 for value in agents.values() if value in DONE_STATES)
        broadcast(
            self.review.pk,
            {
                "type": "review.progress",
                "review_id": self.review.pk,
                "agent": agent,
                "state": agents[agent],
                "agents": agents,
                "completed": completed,
                "total": TOTAL_AGENTS,
                "status": "running",
            },
        )

    def _save(self):
        from apps.reviews.models import Review

        # Keep the caller's in-memory row in step too. It is the same object the
        # review service later saves whole, and a stale `progress` on it would
        # overwrite these updates at the end of every review (found live: the
        # finished event reported 0/5).
        self.review.progress = dict(self.agents)
        Review.objects.filter(pk=self.review.pk).update(progress=dict(self.agents))


def announce_finished(review):
    """The final event: the socket's cue to fetch the finished review."""
    event = snapshot(review)
    event["type"] = "review.finished"
    broadcast(review.pk, event)
