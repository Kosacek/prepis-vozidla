#!/usr/bin/env bash
set -euo pipefail
echo "=== evidence (úkony tracker) entrypoint ==="
echo "DATA_DIR=${DATA_DIR:-/data}"
chmod -R 777 "${DATA_DIR:-/data}" || echo "WARN: chmod failed"
echo "==========================================="
# SQLite is a single file => ONE gunicorn worker (multi-process would contend on
# the DB lock). gthread threads handle concurrency for this low-traffic app.
exec gunicorn "app:application" \
    --bind "0.0.0.0:${HTTP_PORT:-8090}" \
    --workers 1 \
    --threads 4 \
    --worker-class gthread \
    --timeout 60 \
    --graceful-timeout 30 \
    --forwarded-allow-ips='*' \
    --access-logfile - \
    --error-logfile -
