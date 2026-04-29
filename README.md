# Screenloop

Screenloop is a lightweight self-hosted media playlist daemon for local TVs and signage screens. It uploads videos, prepares TV-safe MP4/H.264/AAC copies, manages playlists, monitors DLNA/UPnP renderers, and pushes playback to Samsung, LG, and generic DLNA TVs.

The project is intended to grow into a modern open-source alternative to Home Media Server for local media streaming, playlist automation, and multi-screen control.

## Quick Start

```bash
cp .env.example .env
# edit SCREENLOOP_PASSWORD and SCREENLOOP_SECRET_KEY
docker compose up --build
```

Open `http://localhost:8099` and sign in with the credentials from `.env`.

`network_mode: host` is intentional: SSDP discovery and TV access to local stream URLs work more reliably on the host network.

## Configuration

Important environment variables:

- `SCREENLOOP_USER` / `SCREENLOOP_PASSWORD` - Basic Auth credentials.
- `SCREENLOOP_SECRET_KEY` - required for CSRF and signed stream URLs.
- `SCREENLOOP_HTTP_PORT` - web UI and media stream port, default `8099`.
- `SCREENLOOP_ADVERTISE_HOST` - optional IP advertised to TVs.
- `SCREENLOOP_DATA_DIR` - root data directory, `/data` in Docker.
- `SCREENLOOP_MAX_UPLOAD_BYTES` - upload limit, default 2 GiB.

Legacy `GEZZDLNA_*` variables still work as deprecated fallbacks. New deployments should use `SCREENLOOP_*`.

## Security

Screenloop is designed for trusted LAN use. Do not expose it directly to the public Internet. Use a reverse proxy with TLS and network-level access control if remote access is required.

The app refuses weak/default passwords unless `SCREENLOOP_ALLOW_INSECURE_AUTH=true` is explicitly set for local testing. Stream URLs are signed, POST forms use CSRF tokens, and the web UI adds basic security headers.

## Data

Docker stores data in the `screenloop-data` volume:

- `/data/db/screenloop.sqlite3` - SQLite state.
- `/data/media` - uploaded originals.
- `/data/transcoded` - TV-safe MP4 copies.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
SCREENLOOP_PASSWORD=dev-password SCREENLOOP_SECRET_KEY=dev-secret-change-me python -m screenloop
```

Run checks:

```bash
python3 -m py_compile dlna_push.py screenloop/*.py tests/test_core.py
python3 -m unittest discover -s tests
```

## Release Flow

Development is staged through `dev`. Test changes there first and use the `ghcr.io/gezzydax/screenloop:dev` image for integration checks. Merge `dev` into `main` through a pull request when ready.

`main` is the stable branch and publishes `latest`. Release Please uses Conventional Commits on `main` to open release PRs; merging a release PR creates the version tag, and the Docker workflow publishes versioned GHCR tags such as `0.1.0`.

## Legacy CLI

`dlna_push.py` is deprecated and kept temporarily as a fallback for direct one-off DLNA pushes. The web daemon is the supported interface and the CLI is planned for removal or archival after the daemon stabilizes.
