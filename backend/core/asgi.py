"""ASGI entrypoint.

Serves HTTP through Django and WebSockets through Channels. The one socket is
/ws/reviews/<id>/, which authenticates with a JWT in its first message (see
apps/reviews/consumers.py) rather than through the URL or a session cookie.
"""

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import OriginValidator
from django.conf import settings
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

# Initialised before importing anything that touches the app registry.
django_asgi_app = get_asgi_application()

from apps.reviews.routing import websocket_urlpatterns  # noqa: E402 - needs the registry

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # The frontend's origins, not ALLOWED_HOSTS: the page is served from Vercel
        # and the socket from Render, so the backend's own host never matches.
        "websocket": OriginValidator(
            URLRouter(websocket_urlpatterns), settings.WEBSOCKET_ALLOWED_ORIGINS
        ),
    }
)
