"""The shared Key Value's connection budget, and the fences between the two apps.

CodeSage shares one free Render Key Value (50 connections) with CareBridge and may
use at most 15. The caps live in settings; these tests fail if a default drifts
past the budget, and check against real Redis that the cache pool holds its cap
under concurrent use.
"""

import threading
from unittest import mock

from django.conf import settings
from django.core.cache import cache

from core import infra
from core import settings as configured  # as loaded: conftest swaps the channel layer

BUDGET = 15


def worst_case_connections():
    """Mirror of the budget table in core/settings.py."""
    cache_pool = settings.REDIS_CACHE_MAX_CONNECTIONS
    channels = settings.REDIS_CHANNELS_MAX_CONNECTIONS
    producer = settings.CELERY_BROKER_POOL_LIMIT
    web = cache_pool + channels + producer
    worker = settings.REDIS_BROKER_MAX_CONNECTIONS + producer + cache_pool + channels
    return web + worker


def test_the_worst_case_fits_the_budget():
    assert worst_case_connections() <= BUDGET


def test_every_client_is_capped():
    options = settings.CACHES["default"]["OPTIONS"]
    assert options["pool_class"] == "core.redis_pool.SharedBlockingConnectionPool"
    assert options["max_connections"] == settings.REDIS_CACHE_MAX_CONNECTIONS

    (host,) = configured.CHANNEL_LAYERS["default"]["CONFIG"]["hosts"]
    assert host["max_connections"] == settings.REDIS_CHANNELS_MAX_CONNECTIONS

    transport = settings.CELERY_BROKER_TRANSPORT_OPTIONS
    assert transport["max_connections"] == settings.REDIS_BROKER_MAX_CONNECTIONS
    # Results are never written, so the backend never opens a connection.
    assert settings.CELERY_TASK_IGNORE_RESULT is True


def test_every_key_carries_the_codesage_prefix():
    prefix = settings.REDIS_KEY_PREFIX
    assert settings.CACHES["default"]["KEY_PREFIX"] == prefix
    assert configured.CHANNEL_LAYERS["default"]["CONFIG"]["prefix"] == f"{prefix}:asgi"
    assert settings.CELERY_BROKER_TRANSPORT_OPTIONS["global_keyprefix"] == f"{prefix}:"
    assert settings.CELERY_RESULT_BACKEND_TRANSPORT_OPTIONS["global_keyprefix"] == f"{prefix}:"


def live_connections(name):
    """Connections the Redis server sees under one client name."""
    import redis

    probe = redis.Redis.from_url(settings.REDIS_URL)
    try:
        return sum(1 for client in probe.client_list() if client.get("name") == name)
    finally:
        probe.close()


def test_the_cache_holds_its_cap_across_threads_not_per_thread():
    """Sixteen threads, each with its own Django cache client, share two connections.

    Counted on the Redis server by client name. Django's cache handler is
    thread-local, so a per-client pool would show one connection per thread here
    (it did, in the load run that found this).
    """
    name = settings.CACHES["default"]["OPTIONS"]["client_name"]
    cache.set("budget-probe", "x", timeout=30)
    errors = []
    peak = []
    barrier = threading.Barrier(16)

    def hammer():
        from django.core.cache import caches

        try:
            barrier.wait()
            for _ in range(25):
                assert caches["default"].get("budget-probe") == "x"
            peak.append(live_connections(name))
        except Exception as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=hammer) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert 0 < max(peak) <= settings.REDIS_CACHE_MAX_CONNECTIONS


def test_parallel_progress_reports_send_one_at_a_time():
    """Agents report from parallel threads; each send would otherwise be its own pool."""
    from apps.reviews import progress

    active, overlaps = [], []

    def slow_send(*_args, **_kwargs):
        active.append(1)
        overlaps.append(len(active))
        threading.Event().wait(0.02)
        active.pop()

    with mock.patch.object(progress, "async_to_sync", return_value=slow_send):
        threads = [
            threading.Thread(target=progress.broadcast, args=(1, {"type": "review.progress"}))
            for _ in range(6)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert max(overlaps) == 1


# ----------------------------------------------------------- URL checks


def test_the_database_index_is_read_from_the_path_or_the_query():
    assert infra.redis_db("redis://host:6379") == 0
    assert infra.redis_db("redis://host:6379/1") == 1
    assert infra.redis_db("rediss://default:pw@host:6379/3") == 3
    assert infra.redis_db("redis://host:6379?db=2") == 2


def test_only_a_non_zero_index_is_accepted_in_production():
    assert "database 0" in infra.redis_problem("redis://host:6379/0")
    assert "not set" in infra.redis_problem("")
    assert infra.redis_problem("redis://host:6379/1") == ""


def test_only_neon_is_accepted_as_the_production_database():
    neon = "postgresql://u:p@ep-cool-name-123-pooler.us-west-2.aws.neon.tech/db?sslmode=require"
    assert infra.neon_problem(neon) == ""
    assert infra.is_neon_pooler(neon)
    assert not infra.is_neon_pooler(neon.replace("-pooler", ""))
    assert "not Neon" in infra.neon_problem("postgres://u:p@dpg-x.oregon-postgres.render.com/d")
    assert "not set" in infra.neon_problem("")
