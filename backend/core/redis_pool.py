"""One Redis connection pool per process for the Django cache.

Django keeps a cache client per THREAD (the cache handler is thread-local), and
each client builds its own pool. So `max_connections` on the cache capped each
thread, not the process: twenty webhook threads opened twenty connections in a
load run (docs/DEPLOY.md). On a Key Value with 50 connections shared between two
apps, the cap has to hold per process, so every client here gets the same pool.
"""

import threading

import redis


class SharedBlockingConnectionPool(redis.BlockingConnectionPool):
    """`from_url` hands back one pool per (url, options), whichever thread asks.

    Blocking, so a thread that finds every connection busy waits up to `timeout`
    seconds for one instead of opening another.
    """

    _shared = {}
    _lock = threading.Lock()

    @classmethod
    def from_url(cls, url, **kwargs):
        key = (url, tuple(sorted(kwargs.items())))
        with cls._lock:
            pool = cls._shared.get(key)
            if pool is None:
                pool = cls._shared[key] = super().from_url(url, **kwargs)
            return pool
