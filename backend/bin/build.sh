#!/usr/bin/env bash
# Render build command (root directory: backend):  bash bin/build.sh
#
# Each step prints how long it took, because builds draw on a 500-minute monthly
# pipeline budget shared with every other service on the account (docs/DEPLOY.md).

set -euo pipefail

step() {
    local started=$SECONDS
    echo "==> $*"
    "$@"
    echo "==> took $((SECONDS - started))s: $*"
}

step pip install -r requirements.txt
step python manage.py collectstatic --noinput
step python manage.py migrate --noinput
# Rotated and signed-out refresh tokens pile up in the blacklist tables; every
# deploy prunes the ones that have expired anyway.
step python manage.py flushexpiredtokens

echo "==> build finished in ${SECONDS}s"
