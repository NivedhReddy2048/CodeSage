"""Django settings for CodeSage.

Local development reads from backend/.env (see .env.example). Every value that
differs between environments comes from an environment variable, so the Phase 7
production deploy only needs to supply env vars, not a different settings file.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:3000"]),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-dev-key-change-me-at-least-32-chars")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

# Application definition

DJANGO_APPS = [
    # daphne must precede staticfiles so runserver serves over ASGI.
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "drf_spectacular",
    "channels",
]

LOCAL_APPS = [
    "apps.accounts",
    "apps.repos",
    "apps.ingestion",
    "apps.reviews",
    "apps.agents",
    "apps.notifications",
    "apps.analytics",
    "apps.audit",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"
ASGI_APPLICATION = "core.asgi.application"

# Database — Postgres with pgvector (docker compose locally, Neon in production)

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://codesage:codesage@localhost:5432/codesage",
    )
}

# Channel layer — Redis (docker compose locally, Upstash in production)

REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}

# Cache — the same Redis. Needed for real: GitHub App installation tokens are cached
# here until shortly before they expire (see apps/repos/github_app.py). Django ships
# this backend natively from 4.0, so it costs no extra dependency.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Login is GitHub-only, so the user model carries a github_id instead of relying on
# username as identity. Set before the first migration of this project's own apps.
AUTH_USER_MODEL = "accounts.User"

# DRF + OpenAPI

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}

# Signed with JWT_SIGNING_KEY rather than DJANGO_SECRET_KEY, so rotating one does not
# invalidate the other. Falls back to SECRET_KEY to keep local setup to one variable.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "SIGNING_KEY": env("JWT_SIGNING_KEY", default=SECRET_KEY),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# GitHub OAuth App — user login only. The GitHub App that owns webhooks and PR
# comments is separate and arrives in phase 2 (spec section 13).
GITHUB_CLIENT_ID = env("GITHUB_CLIENT_ID", default="")
GITHUB_CLIENT_SECRET = env("GITHUB_CLIENT_SECRET", default="")

# Where GitHub sends the browser after the user authorises. This is a FRONTEND route,
# not a backend one: the SPA reads the code and POSTs it to the callback endpoint, so
# issued JWTs never travel in a URL. Must match the OAuth App's callback URL exactly.
GITHUB_OAUTH_REDIRECT_URI = env(
    "GITHUB_OAUTH_REDIRECT_URI", default="http://localhost:3000/auth/callback"
)

# GitHub App — the PR loop (spec section 13). Separate identity from the OAuth App above:
# this one owns webhooks, repository reads and PR comments, and posts as the bot.
GITHUB_APP_ID = env("GITHUB_APP_ID", default="")

# GitHub's docs say "Use of the client ID is recommended" for the JWT issuer, with the
# numeric App ID still accepted. Prefer this when set; the App ID is the fallback.
GITHUB_APP_CLIENT_ID = env("GITHUB_APP_CLIENT_ID", default="")

# Two ways to supply the private key, because the environments differ. Locally it is a
# gitignored file; in production there is no filesystem for it, so the PEM contents
# travel in an env var (escaped newlines are unescaped on read).
GITHUB_APP_PRIVATE_KEY_PATH = env("GITHUB_APP_PRIVATE_KEY_PATH", default="")
GITHUB_APP_PRIVATE_KEY = env("GITHUB_APP_PRIVATE_KEY", default="")

# Shared with GitHub so it can sign webhook deliveries; the receiver verifies
# X-Hub-Signature-256 against it.
GITHUB_WEBHOOK_SECRET = env("GITHUB_WEBHOOK_SECRET", default="")

# Run webhook follow-up work inline instead of on a thread. Tests set this so they do
# not race a background thread; it mirrors Celery's task_always_eager, which spec
# section 7 names as the fallback for lightweight jobs.
BACKGROUND_TASKS_EAGER = env.bool("BACKGROUND_TASKS_EAGER", default=False)

SPECTACULAR_SETTINGS = {
    "TITLE": "CodeSage API",
    "DESCRIPTION": "Multi-agent code review pipeline for GitHub pull requests.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
