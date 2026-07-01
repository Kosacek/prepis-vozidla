# Stage 1: deps
FROM python:3.12-slim AS deps
ENV PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Stage 2: runtime
FROM python:3.12-slim AS runtime
ENV TZ=Europe/Prague PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HTTP_PORT=8090 DATA_DIR=/data
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
ARG CACHEBUST=2026-07-01-evidence-editable-firma-on-ukon
COPY app.py config.py db.py ./
COPY repositories ./repositories
COPY services ./services
COPY routes ./routes
COPY templates ./templates
COPY static ./static
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && mkdir -p /data && echo "CACHEBUST=$CACHEBUST" > /etc/cachebust
EXPOSE 8090
VOLUME ["/data"]
ENTRYPOINT ["/entrypoint.sh"]
