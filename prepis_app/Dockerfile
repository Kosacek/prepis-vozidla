# Stage 1: build deps. Build toolchain present so any C-extension wheel that
# isn't prebuilt for the target arch can fall back to a source build.
FROM python:3.12-slim AS deps
ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev libjpeg-dev zlib1g-dev \
    libfreetype6-dev ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Stage 2: runtime
FROM python:3.12-slim AS runtime
ENV TZ=Europe/Prague \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HTTP_PORT=8089 \
    DATA_DIR=/data
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo zlib1g libfreetype6 ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

# Installed Python packages from the deps stage
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Cache buster — bump on every source change shipped to the NAS. The QNAP
# SMB share can keep a stale snapshot across builds; changing this value
# forces all subsequent layers (the COPYs below) to rebuild.
ARG CACHEBUST=2026-07-11-zadosti-bigger-all-steps

# App code (read-only assets baked into the image; writable state lives on /data)
COPY app.py ./app.py
COPY tracker_push.py ./tracker_push.py
COPY ppd.py ./ppd.py
COPY version.py ./version.py
COPY VERSION ./VERSION
COPY templates ./templates
COPY static ./static
COPY pdfs ./pdfs
COPY docker/entrypoint.sh /entrypoint.sh

RUN chmod +x /entrypoint.sh \
 && mkdir -p /data \
 && echo "CACHEBUST=$CACHEBUST" > /etc/cachebust \
 && cat /etc/cachebust

# Run as root (compose sets user: "0:0"): the /data bind mount is created by
# QNAP Container Station over SMB with unpredictable ownership; the entrypoint
# chmods it at startup. Same rationale as the hunter reference.
EXPOSE 8089
VOLUME ["/data"]
ENTRYPOINT ["/entrypoint.sh"]
