"""WebSocket at /ws/reviews/<id>/: live pipeline progress for one review.

Authentication is the first message, not the URL. A browser WebSocket cannot set an
Authorization header, and the usual workaround - the token in the query string -
puts a bearer credential into server and proxy access logs. So the socket opens,
the client sends `{"type": "auth", "token": "<access JWT>"}`, and nothing is sent
until that checks out:

  - an invalid or expired token closes with 4401;
  - a review that does not exist, or belongs to an organisation the user is not a
    member of, closes with 4404 - the same answer for both, as with the REST API,
    so the socket cannot be used to probe for other tenants' review ids;
  - no auth message within AUTH_TIMEOUT seconds closes with 4401.

Only then does the socket join the review's group, so a user can never receive an
event for a review outside their organisations.
"""

import asyncio
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from apps.reviews import progress

logger = logging.getLogger(__name__)

AUTH_TIMEOUT = 10
CLOSE_UNAUTHENTICATED = 4401
CLOSE_NOT_FOUND = 4404


class ReviewProgressConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.review_id = int(self.scope["url_route"]["kwargs"]["review_id"])
        self.group = None
        await self.accept()
        self.auth_timer = asyncio.ensure_future(self._expire_unauthenticated())

    async def _expire_unauthenticated(self):
        await asyncio.sleep(AUTH_TIMEOUT)
        if self.group is None:
            await self.close(code=CLOSE_UNAUTHENTICATED)

    async def receive_json(self, content, **kwargs):
        if self.group is not None:
            return  # The socket is one-way once authenticated.

        if not isinstance(content, dict) or content.get("type") != "auth":
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return

        user_id = _user_id_from(content.get("token"))
        if user_id is None:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return

        state = await self._snapshot_if_visible(user_id)
        if state is None:
            await self.close(code=CLOSE_NOT_FOUND)
            return

        self.auth_timer.cancel()
        self.group = progress.group_name(self.review_id)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.send_json(state)

    async def disconnect(self, code):
        timer = getattr(self, "auth_timer", None)
        if timer is not None:
            timer.cancel()
        if getattr(self, "group", None):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def review_event(self, message):
        await self.send_json(message["event"])

    @database_sync_to_async
    def _snapshot_if_visible(self, user_id):
        from apps.reviews.models import Review

        review = (
            Review.objects.filter(
                pk=self.review_id,
                pull_request__repository__organization__memberships__user_id=user_id,
                pull_request__repository__organization__memberships__user__is_active=True,
            )
            .distinct()
            .first()
        )
        return progress.snapshot(review) if review else None


def _user_id_from(token):
    if not token or not isinstance(token, str):
        return None
    try:
        return AccessToken(token).get("user_id")
    except TokenError:
        return None
