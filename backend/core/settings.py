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
    # Required by pgvector's HnswIndex, which builds on the postgres index machinery.
    "django.contrib.postgres",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    # Rotated and signed-out refresh tokens are recorded here and refused. Expired
    # rows are pruned by `manage.py flushexpiredtokens` (run it in the build command).
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "drf_spectacular",
    "channels",
]

LOCAL_APPS = [
    "apps.accounts",
    "apps.repos",
    "apps.ingestion",
    "apps.reviews",
    # apps.agents is deliberately NOT installed. It is a plain Python package, not a
    # Django app: no models, no views, no migrations. Registering it would require an
    # AppConfig, which would be the one Django import in a package whose whole point
    # is not having any (the phase 4 architecture note). Leaving it out makes that
    # rule grep-verifiable instead of a convention.
    "apps.notifications",
    "apps.analytics",
    "apps.audit",
    "apps.evaluation",
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
        # Simple JWT plus the workspace switcher's X-Organization-Id header.
        "apps.accounts.authentication.OrganizationAwareJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}

# Signed with JWT_SIGNING_KEY rather than DJANGO_SECRET_KEY, so rotating one does not
# invalidate the other. Falls back to SECRET_KEY to keep local setup to one variable.
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    # Without this, rotation was cosmetic: a rotated refresh token still worked for
    # its full lifetime (verified against the live backend while fixing #97).
    "BLACKLIST_AFTER_ROTATION": True,
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

# URL slug of the App, used to build its install link. Optional: when unset it is
# fetched once from GET /app and cached, since the slug never changes.
GITHUB_APP_SLUG = env("GITHUB_APP_SLUG", default="")

# Two ways to supply the private key, because the environments differ. Locally it is a
# gitignored file; in production there is no filesystem for it, so the PEM contents
# travel in an env var (escaped newlines are unescaped on read).
GITHUB_APP_PRIVATE_KEY_PATH = env("GITHUB_APP_PRIVATE_KEY_PATH", default="")
GITHUB_APP_PRIVATE_KEY = env("GITHUB_APP_PRIVATE_KEY", default="")

# Shared with GitHub so it can sign webhook deliveries; the receiver verifies
# X-Hub-Signature-256 against it.
GITHUB_WEBHOOK_SECRET = env("GITHUB_WEBHOOK_SECRET", default="")

# ---------------------------------------------------------------------------
# Ingestion and embeddings (phase 3, spec section 6)
# ---------------------------------------------------------------------------

GEMINI_API_KEY = env("GEMINI_API_KEY", default="")

EMBEDDING_MODEL = env("EMBEDDING_MODEL", default="gemini-embedding-001")

# 1536, not the model's 3072 default. pgvector's hnsw and ivfflat indexes cap at 2000
# dimensions, so a 3072-dim column is storable but NOT indexable and every similarity
# search would silently become a sequential scan. Verified against the live API on
# 2026-10-18. Changing this requires a migration: it is the column's declared width.
EMBEDDING_DIMENSIONS = env.int("EMBEDDING_DIMENSIONS", default=1536)

# Gemini's batch embedding endpoint accepts up to 100 inputs; 50 keeps individual
# requests small enough to retry cheaply.
EMBEDDING_BATCH_SIZE = env.int("EMBEDDING_BATCH_SIZE", default=50)
EMBEDDING_MAX_RETRIES = env.int("EMBEDDING_MAX_RETRIES", default=5)
EMBEDDING_BACKOFF_SECONDS = env.float("EMBEDDING_BACKOFF_SECONDS", default=2.0)

# Free-tier guardrails. Neon's free plan is 0.5 GB, and at 1536 dimensions each
# embedding is about 6 KB, so the chunk cap is the main lever on storage: 4000 chunks
# is roughly 24 MB of vectors per repository.
INGESTION_MAX_FILE_BYTES = env.int("INGESTION_MAX_FILE_BYTES", default=256 * 1024)
INGESTION_MAX_CHUNKS_PER_REPO = env.int("INGESTION_MAX_CHUNKS_PER_REPO", default=4000)
INGESTION_MAX_CHUNK_CHARS = env.int("INGESTION_MAX_CHUNK_CHARS", default=8000)
INGESTION_MAX_ARCHIVE_BYTES = env.int("INGESTION_MAX_ARCHIVE_BYTES", default=100 * 1024 * 1024)

# Celery, co-located with the web process on Render's free tier (spec section 7).
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_TIME_LIMIT = env.int("CELERY_TASK_TIME_LIMIT", default=30 * 60)

# ---------------------------------------------------------------------------
# Review pipeline (phase 4, spec sections 5 and 14)
# ---------------------------------------------------------------------------

GROQ_API_KEY = env("GROQ_API_KEY", default="")

# The spec named llama-3.3-70b-versatile, but GET /v1/models does not list it for a
# current free key even though Groq's docs still show it as production. Entitlement
# beats documentation, so the primary is the largest production model the key can
# actually call. qwen3.8-27b is faster but Groq labels it preview ("should not be
# used in production") and it emits invalid JSON without json_object mode.
# Phase 8: fixtures, the category map and cached results (docs/EVALUATION.md).
EVAL_ROOT = Path(env("EVAL_ROOT", default=str(BASE_DIR.parent / "eval")))

REVIEW_PRIMARY_MODEL = env("REVIEW_PRIMARY_MODEL", default="openai/gpt-oss-120b")

# Thinking models are barred from the review path: gemini-3.8-flash took 96s and
# gemini-flash-latest 143s to emit one token (spec section 14).
REVIEW_FALLBACK_MODEL = env("REVIEW_FALLBACK_MODEL", default="gemini-flash-lite-latest")

# Model tiering. Groq reports 8000 TPM per model: the big model runs the security and
# correctness passes, and the cheap one handles classification, grounding and test
# coverage.
REVIEW_CHEAP_MODEL = env("REVIEW_CHEAP_MODEL", default="openai/gpt-oss-20b")

# Tokens one review may spend on each model, with headroom under that model's 8000
# TPM ceiling so a review degrades predictably instead of 429-ing part way.
REVIEW_TOKEN_BUDGET = env.int("REVIEW_TOKEN_BUDGET", default=6500)

# Live Groq rate-limit headers report 8000 tokens/minute, so an unbounded diff would
# be rejected outright or starve the next review. Roughly 24 KB of diff is ~6k
# tokens, leaving headroom for the prompt and the response.
REVIEW_MAX_DIFF_BYTES = env.int("REVIEW_MAX_DIFF_BYTES", default=24000)
REVIEW_MAX_FINDINGS = env.int("REVIEW_MAX_FINDINGS", default=25)
# Inline comments on the diff per review. Blocking findings come first, so a cap
# trims nits; past a dozen or so, inline comments bury the conversation.
REVIEW_MAX_INLINE_COMMENTS = env.int("REVIEW_MAX_INLINE_COMMENTS", default=15)
REVIEW_REQUEST_TIMEOUT = env.int("REVIEW_REQUEST_TIMEOUT", default=90)
REVIEW_MAX_RETRIES = env.int("REVIEW_MAX_RETRIES", default=3)
REVIEW_BACKOFF_SECONDS = env.float("REVIEW_BACKOFF_SECONDS", default=2.0)
REVIEW_BREAKER_FAILURE_THRESHOLD = env.int("REVIEW_BREAKER_FAILURE_THRESHOLD", default=3)
REVIEW_BREAKER_RESET_SECONDS = env.float("REVIEW_BREAKER_RESET_SECONDS", default=300.0)

# USD per 1,000,000 tokens, at each provider's PAID tier.
#
# Groq: https://console.groq.com/docs/models, "Production Models" table, column
#   "PRICE PER 1M TOKENS" - checked 2026-10-18. Note groq.com/pricing carries no
#   figures (JavaScript-rendered); the docs page is the official source.
# Gemini: https://ai.google.dev/gemini-api/docs/pricing - checked 2026-10-16.
#
# These are estimates for display only. The project runs entirely on free tiers, so
# actual spend is zero; every surface that shows a cost says "est. at paid-tier
# rates" (spec section 14).
LLM_PRICING = {
    "openai/gpt-oss-120b": {"input": 0.15, "output": 0.60},
    "openai/gpt-oss-20b": {"input": 0.075, "output": 0.30},
    "gemini-flash-lite-latest": {"input": 0.10, "output": 0.40},
    "gemini-embedding-001": {"input": 0.20, "output": 0.00},
}

# Fixed, not fetched at runtime: a review's recorded cost must not change when FX
# moves, and a currency API is one more thing that can fail during a demo.
# Source: ECB reference rate via api.frankfurter.dev - 1 USD = 95.06 INR on 2026-10-15.
USD_TO_INR = env.float("USD_TO_INR", default=95.06)
USD_TO_INR_AS_OF = "2026-10-15"

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

# The workspace switcher's header. Not a CORS-safelisted header, so the browser
# preflights it; without it here every request from a chosen workspace failed before
# reaching Django (found in a real browser, not by the test suite).
from corsheaders.defaults import default_headers  # noqa: E402

CORS_ALLOW_HEADERS = (*default_headers, "x-organization-id")
