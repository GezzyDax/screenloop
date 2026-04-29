FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SCREENLOOP_DATA_DIR=/data \
    SCREENLOOP_HTTP_HOST=0.0.0.0 \
    SCREENLOOP_HTTP_PORT=8099

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd --system --create-home --uid 10001 screenloop \
    && mkdir -p /data \
    && chown -R screenloop:screenloop /data

COPY screenloop ./screenloop
COPY dlna_push.py ./

VOLUME ["/data"]
EXPOSE 8099

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; port=os.environ.get('SCREENLOOP_HTTP_PORT','8099'); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=3)"

USER screenloop

CMD ["python", "-m", "screenloop"]
