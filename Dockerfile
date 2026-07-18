# syntax=docker/dockerfile:1

FROM node:26-alpine AS frontend-build

WORKDIR /frontend
COPY frontend/package*.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY frontend ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine AS frontend

ENV SCREENLOOP_UI_PORT=8098 \
    SCREENLOOP_BACKEND_URL=http://127.0.0.1:8099 \
    SCREENLOOP_MAX_UPLOAD_BYTES=2147483648

# Pull patched Alpine packages at build time instead of trusting whatever
# apk index was current when the base image layer was last published.
# The base image already drops to the unprivileged nginx user; apk needs
# root, so switch back explicitly afterwards.
USER root
RUN apk update --no-cache && apk upgrade --no-cache
USER nginx

COPY --from=frontend-build /frontend/dist /usr/share/nginx/html
COPY frontend/nginx.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 8098

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null "http://127.0.0.1:${SCREENLOOP_UI_PORT}/" || exit 1

FROM python:3.13-alpine AS backend-deps

RUN apk update --no-cache && apk upgrade --no-cache

WORKDIR /build
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install --prefix=/install -r requirements.txt

FROM python:3.13-alpine AS node

ARG SCREENLOOP_VERSION=0.3.0-dev
ARG SCREENLOOP_REVISION=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SCREENLOOP_NODE_DATA_DIR=/data \
    SCREENLOOP_NODE_HTTP_PORT=8099 \
    SCREENLOOP_VERSION=${SCREENLOOP_VERSION} \
    SCREENLOOP_REVISION=${SCREENLOOP_REVISION}

LABEL org.opencontainers.image.title="Screenloop Node" \
      org.opencontainers.image.description="Screenloop remote node agent" \
      org.opencontainers.image.source="https://github.com/GezzyDax/screenloop"

RUN apk update --no-cache && apk upgrade --no-cache \
    && apk add --no-cache iputils

WORKDIR /app
COPY --from=backend-deps /install /usr/local

RUN addgroup -S screenloop \
    && adduser -S -D -u 10001 -G screenloop -h /home/screenloop screenloop \
    && mkdir -p /data \
    && chown -R screenloop:screenloop /data

COPY screenloop ./screenloop

VOLUME ["/data"]
EXPOSE 8099

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; port=os.environ.get('SCREENLOOP_NODE_HTTP_PORT','8099'); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=3)"

USER screenloop

CMD ["python", "-m", "screenloop.node_agent"]

FROM python:3.13-alpine AS backend

ARG SCREENLOOP_VERSION=0.3.0-dev
ARG SCREENLOOP_REVISION=unknown

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SCREENLOOP_DATA_DIR=/data \
    SCREENLOOP_HTTP_HOST=0.0.0.0 \
    SCREENLOOP_HTTP_PORT=8099 \
    SCREENLOOP_VERSION=${SCREENLOOP_VERSION} \
    SCREENLOOP_REVISION=${SCREENLOOP_REVISION}

LABEL org.opencontainers.image.title="Screenloop" \
      org.opencontainers.image.description="Local TV playlist daemon and DLNA control panel" \
      org.opencontainers.image.source="https://github.com/GezzyDax/screenloop" \
      org.opencontainers.image.version="${SCREENLOOP_VERSION}" \
      org.opencontainers.image.revision="${SCREENLOOP_REVISION}"

RUN apk update --no-cache && apk upgrade --no-cache \
    && apk add --no-cache ffmpeg iproute2 iputils

WORKDIR /app
COPY --from=backend-deps /install /usr/local

RUN addgroup -S screenloop \
    && adduser -S -D -u 10001 -G screenloop -h /home/screenloop screenloop \
    && mkdir -p /data \
    && chown -R screenloop:screenloop /data

COPY screenloop ./screenloop

VOLUME ["/data"]
EXPOSE 8099

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; port=os.environ.get('SCREENLOOP_HTTP_PORT','8099'); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=3)"

USER screenloop

CMD ["python", "-m", "screenloop"]
