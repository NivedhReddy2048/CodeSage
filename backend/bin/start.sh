#!/usr/bin/env bash
# Render start command (root directory: backend):  bash bin/start.sh
#
# Render's free tier has no background-worker service type, so the Celery worker
# runs beside Daphne in the one container (spec section 7). Two rules keep that
# honest:
#
#   - If either process exits, the other is stopped and the container exits with
#     its status. Render then restarts both, instead of leaving a web process that
#     accepts webhooks with no worker to run them.
#   - Render's SIGTERM (deploy, restart, spin-down) is forwarded to both, so Daphne
#     closes its sockets and the worker gets its warm shutdown.
#
# The worker is lean on purpose: one process (solo pool), and none of the
# worker-to-worker chatter (gossip, mingle, heartbeat) a single worker has nobody
# to share with. Each of those would otherwise hold Redis connections and traffic
# on a shared 50-connection, 25 MB Key Value.

set -uo pipefail

celery -A core worker \
    --pool=solo \
    --without-gossip \
    --without-mingle \
    --without-heartbeat \
    --loglevel="${CELERY_LOG_LEVEL:-info}" &
worker=$!

daphne --bind 0.0.0.0 --port "${PORT:-8000}" core.asgi:application &
web=$!

stop() {
    trap - TERM INT
    kill -TERM "$web" "$worker" 2>/dev/null
}
trap stop TERM INT

# Returns when the first child exits, or early when a trapped signal arrives.
wait -n
status=$?
stop
# Let both finish shutting down before the container goes.
wait
exit "$status"
