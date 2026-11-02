"""Checks on the hosted services production depends on, run while settings load.

Pure functions of a URL, so they are testable without a deploy, and raised as
ImproperlyConfigured from settings so a wrong value stops the build (migrate runs
in bin/build.sh) instead of surfacing as odd behaviour days later.
"""

from urllib.parse import parse_qs, urlsplit

NEON_HOST_SUFFIX = ".neon.tech"


def neon_problem(database_url):
    """Why `database_url` is not an acceptable production database, or "".

    Neon only. Render's free Postgres is deleted 30 days after creation (that is
    how CareBridge's database went), and SQLite on a free web service lives on a
    disk that is wiped on every deploy and restart.
    """
    if not database_url:
        return "DATABASE_URL is not set. Production needs the Neon connection string."
    parts = urlsplit(database_url)
    host = (parts.hostname or "").lower()
    if not parts.scheme.startswith("postgres"):
        scheme = parts.scheme or "no scheme"
        return f"DATABASE_URL uses {scheme}://; production needs Neon Postgres."
    if not host.endswith(NEON_HOST_SUFFIX):
        return (
            f"DATABASE_URL points at {host or 'no host'}, which is not Neon. Render's free "
            "Postgres expires after 30 days, so CodeSage never uses it."
        )
    return ""


def is_neon_pooler(database_url):
    """Neon's pooled hosts carry `-pooler` in the endpoint name (PgBouncer)."""
    return "-pooler." in (urlsplit(database_url).hostname or "")


def redis_db(redis_url):
    """The logical database a redis:// URL selects: the path, else ?db=, else 0."""
    parts = urlsplit(redis_url)
    path = parts.path.strip("/")
    if path.isdigit():
        return int(path)
    query = parse_qs(parts.query).get("db")
    if query and query[0].isdigit():
        return int(query[0])
    return 0


def redis_problem(redis_url):
    """Why `redis_url` is not acceptable in production, or "".

    The Key Value instance is shared with CareBridge, which uses database 0.
    CodeSage takes its own index so the two apps' Celery queues, results and
    Channels groups never meet (key prefixes are the second fence).
    """
    if not redis_url:
        return "REDIS_URL is not set. Production needs the shared Key Value URL ending in /1."
    if redis_db(redis_url) == 0:
        return (
            "REDIS_URL selects database 0, which CareBridge uses on the shared Key Value. "
            "Append /1 (or another free index) to the URL."
        )
    return ""
