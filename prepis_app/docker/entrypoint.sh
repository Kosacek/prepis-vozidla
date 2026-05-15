#!/usr/bin/env bash
set -euo pipefail

# The /data bind mount can land with arbitrary host ownership when QNAP
# Container Station created it over SMB, so the container may not be able to
# read/write firmy.xlsx, plne_moce/, scans/, output/ even though it owns
# /data inside the image. Running as root (compose user: "0:0") plus this
# chmod at startup is the simplest fix that doesn't touch the host FS.
echo "=== zadosti (přepisy) entrypoint ==="
echo "whoami=$(whoami) uid=$(id -u) gid=$(id -g)"
echo "DATA_DIR=${DATA_DIR:-/data}"
ls -la "${DATA_DIR:-/data}" || true
chmod -R 777 "${DATA_DIR:-/data}" || echo "WARN: chmod failed"
echo "==================================="

# No database, no migrations (unlike hunter's alembic upgrade head).
# The app reads writable paths from DATA_DIR (set to /data via the image
# env / compose) so there is no relative-path rewrite to do either.

# Hand off to gunicorn (PID 1). The app itself wraps wsgi_app in
# werkzeug ProxyFix, so X-Forwarded-Proto/-For/-Host from Cloudflare→nginx
# are honored (https URLs, Secure cookies). --forwarded-allow-ips='*' is
# safe because the container is only reachable on the internal docker
# network. gthread workers + long timeout because the scan endpoints block
# on the Anthropic Vision API (can take 30-45s).
exec gunicorn app:app \
    --bind "0.0.0.0:${HTTP_PORT:-8089}" \
    --workers 2 \
    --threads 4 \
    --worker-class gthread \
    --timeout 180 \
    --graceful-timeout 30 \
    --forwarded-allow-ips='*' \
    --access-logfile - \
    --error-logfile -
