"""Production configuration: what DJANGO_PRODUCTION switches on, and what stays put.

Settings are read once at import, so the production shape is checked in a fresh
interpreter with the env Render would supply, not by patching this process.
"""

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.test import Client
from django.urls import reverse

BACKEND = Path(__file__).resolve().parent.parent

PRODUCTION_ENV = {
    "DJANGO_PRODUCTION": "True",
    "DJANGO_DEBUG": "False",
    "DJANGO_SECRET_KEY": secrets.token_urlsafe(50),
    "JWT_SIGNING_KEY": secrets.token_urlsafe(50),
    "DJANGO_ALLOWED_HOSTS": "",
    "RENDER_EXTERNAL_HOSTNAME": "codesage-api.onrender.com",
    "CORS_ALLOWED_ORIGINS": "https://codesage.vercel.app",
    "DATABASE_URL": (
        "postgres://codesage:pw@ep-quiet-sky-123456-pooler.us-west-2.aws.neon.tech/codesage"
    ),
    "REDIS_URL": "redis://red-abc123:6379/1",
}


def run_in_production(code, **overrides):
    env = {
        **os.environ,
        **PRODUCTION_ENV,
        **overrides,
        "DJANGO_SETTINGS_MODULE": "core.settings",
    }
    return subprocess.run(
        [sys.executable, *code], cwd=BACKEND, env=env, capture_output=True, text=True
    )


def test_production_turns_on_the_secure_defaults():
    script = (
        "import django, json; django.setup(); from django.conf import settings as s; "
        "print(json.dumps({k: getattr(s, k, None) for k in ["
        "'DEBUG', 'ALLOWED_HOSTS', 'CSRF_TRUSTED_ORIGINS', 'WEBSOCKET_ALLOWED_ORIGINS', "
        "'SECURE_PROXY_SSL_HEADER', 'SECURE_SSL_REDIRECT', 'SESSION_COOKIE_SECURE', "
        "'CSRF_COOKIE_SECURE', 'SECURE_HSTS_SECONDS', 'TRUSTED_PROXY_HOPS']} | "
        "{'static': s.STORAGES['staticfiles']['BACKEND']}))"
    )
    result = run_in_production(["-c", script])
    assert result.returncode == 0, result.stderr
    values = json.loads(result.stdout.strip().splitlines()[-1])

    assert values["DEBUG"] is False
    assert values["ALLOWED_HOSTS"] == ["codesage-api.onrender.com"]
    assert values["CSRF_TRUSTED_ORIGINS"] == ["https://codesage.vercel.app"]
    assert values["WEBSOCKET_ALLOWED_ORIGINS"] == ["https://codesage.vercel.app"]
    assert values["SECURE_PROXY_SSL_HEADER"] == ["HTTP_X_FORWARDED_PROTO", "https"]
    assert values["SECURE_SSL_REDIRECT"] is True
    assert values["SESSION_COOKIE_SECURE"] is True
    assert values["CSRF_COOKIE_SECURE"] is True
    assert values["SECURE_HSTS_SECONDS"] == 31_536_000
    assert values["TRUSTED_PROXY_HOPS"] == 3  # measured on Render: CF, Render proxy, app
    assert values["static"] == "whitenoise.storage.CompressedManifestStaticFilesStorage"


def test_production_passes_djangos_deployment_checklist():
    """`check --deploy` at warning level: nothing left for someone to wave through."""
    result = run_in_production(["manage.py", "check", "--deploy", "--fail-level", "WARNING"])

    assert result.returncode == 0, result.stdout + result.stderr


def test_production_uses_neon_through_its_pooler_with_short_connections():
    script = (
        "import django, json; django.setup(); from django.conf import settings as s; "
        "d = s.DATABASES['default']; "
        "print(json.dumps({'host': d['HOST'], 'age': d['CONN_MAX_AGE'], "
        "'cursors': d.get('DISABLE_SERVER_SIDE_CURSORS'), 'options': d['OPTIONS']}))"
    )
    result = run_in_production(["-c", script])
    assert result.returncode == 0, result.stderr
    values = json.loads(result.stdout.strip().splitlines()[-1])

    assert values["host"].endswith("-pooler.us-west-2.aws.neon.tech")
    assert values["age"] == 0
    assert values["cursors"] is True
    assert values["options"]["sslmode"] == "require"
    assert values["options"]["prepare_threshold"] is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"DATABASE_URL": ""}, "DATABASE_URL is not set"),
        (
            {"DATABASE_URL": "postgres://u:p@dpg-abc123-a.oregon-postgres.render.com/db"},
            "not Neon",
        ),
        ({"DATABASE_URL": "sqlite:///db.sqlite3"}, "production needs Neon"),
        ({"REDIS_URL": "redis://red-abc123:6379"}, "REDIS_URL: REDIS_URL selects database 0"),
        ({"CELERY_BROKER_URL": "redis://red-abc123:6379/0"}, "CELERY_BROKER_URL"),
    ],
)
def test_production_refuses_to_start_on_the_wrong_data_services(overrides, message):
    """Fails while settings load, so `migrate` in the build stops the deploy."""
    result = run_in_production(["manage.py", "check"], **overrides)

    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr
    assert message in result.stderr


def test_local_development_keeps_plain_http(settings):
    """This process runs with the dev defaults: no proxy trust, no HTTPS redirect."""
    assert settings.TRUSTED_PROXY_HOPS == 0
    assert not hasattr(settings, "SECURE_PROXY_SSL_HEADER") or not settings.SECURE_PROXY_SSL_HEADER
    assert settings.SECURE_SSL_REDIRECT is False


# ------------------------------------------------------------------ health


def test_health_never_touches_the_database():
    """No django_db mark: any query here raises, so this fails if health grows one.

    The keep-warm ping hits health every few minutes; a query would wake Neon's
    scale-to-zero compute every time and spend its monthly compute hours.
    """
    response = Client().get(reverse("health"))

    assert response.status_code == 200


def test_health_answers_plain_http_even_when_https_is_enforced(settings):
    settings.SECURE_SSL_REDIRECT = True

    assert Client().get(reverse("health")).status_code == 200
    assert Client().get(reverse("schema")).status_code == 301


# ---------------------------------------------------------------- websockets


@pytest.mark.django_db
def test_a_websocket_from_a_foreign_origin_is_refused():
    """Refused at the handshake, before the consumer runs.

    django_db only because Channels checks for stale connections on the way out.
    """
    from core.asgi import application

    async def scenario():
        communicator = WebsocketCommunicator(
            application, "/ws/reviews/1/", headers=[(b"origin", b"https://evil.example")]
        )
        connected, _ = await communicator.connect()
        await communicator.disconnect()
        return connected

    assert async_to_sync(scenario)() is False
