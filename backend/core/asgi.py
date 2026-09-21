"""ASGI entrypoint.

Serves HTTP through Django and WebSockets through Channels. The websocket
URLRouter is deliberately empty in Phase 0 — consumers arrive in Phase 6.
"""

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

# Initialised before importing anything that touches the app registry.
django_asgi_app = get_asgi_application()

websocket_urlpatterns = []

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(URLRouter(websocket_urlpatterns)),
    }
)
