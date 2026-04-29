# Screenloop

Screenloop is a lightweight self-hosted media playlist daemon for local TVs and signage screens. It uploads videos, prepares TV-safe MP4/H.264/AAC copies, manages playlists, monitors DLNA/UPnP renderers, and pushes playback to Samsung, LG, and generic DLNA TVs.

The project is intended to grow into a modern open-source alternative to Home Media Server for local media streaming, playlist automation, and multi-screen control.

## Quick Start

One-command install on a Linux host with Docker:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/install.sh)
```

From source:

```bash
cp .env.example .env
# edit SCREENLOOP_BOOTSTRAP_PASSWORD and SCREENLOOP_SECRET_KEY
docker compose up --build
```

From the published GHCR image:

```bash
cp .env.example .env
# edit SCREENLOOP_BOOTSTRAP_PASSWORD and SCREENLOOP_SECRET_KEY
docker compose -f docker-compose.ghcr.yml up -d
```

Update an installed host:

```bash
cd /opt/screenloop
./update.sh
```

Update to the latest dev build:

```bash
cd /opt/screenloop
./update.sh -dev
```

Open `http://localhost:8099` and sign in with the credentials from `.env`.

`network_mode: host` is intentional: SSDP discovery and TV access to local stream URLs work more reliably on the host network.

## Configuration

Important environment variables:

- `SCREENLOOP_BOOTSTRAP_USER` / `SCREENLOOP_BOOTSTRAP_PASSWORD` - first admin account created when the user table is empty.
- `SCREENLOOP_SECRET_KEY` - required for CSRF and signed stream URLs.
- `SCREENLOOP_HTTP_PORT` - web UI and media stream port, default `8099`.
- `SCREENLOOP_ADVERTISE_HOST` - optional single IP advertised to TVs.
- `SCREENLOOP_ADVERTISE_HOSTS` - optional comma-separated IPs for multi-subnet hosts, for example `192.0.2.10,198.51.100.10`.
- `SCREENLOOP_DATA_DIR` - root data directory, `/data` in Docker.
- `SCREENLOOP_MAX_UPLOAD_BYTES` - upload limit, default 2 GiB.
- `SCREENLOOP_ALLOWED_TV_CIDRS` - optional comma-separated TV network allowlist, for example `192.0.2.0/24,198.51.100.0/24`.
- `SCREENLOOP_TRUSTED_PROXY_CIDRS` - reverse proxy IP ranges allowed to supply `X-Forwarded-For`.
- `SCREENLOOP_COOKIE_SECURE` - set to `true` when serving through HTTPS.

Legacy `GEZZDLNA_*` variables still work as deprecated fallbacks. New deployments should use `SCREENLOOP_*`.

## Security

Screenloop is designed for trusted LAN use. Do not expose it directly to the public Internet. Use a reverse proxy with TLS and network-level access control if remote access is required.

The app refuses weak/default bootstrap passwords unless `SCREENLOOP_ALLOW_INSECURE_AUTH=true` is explicitly set for local testing. The web UI uses signed cookie sessions, CSRF protection, role-based access control (`admin`, `operator`, `viewer`), login rate limiting, audit events, and signed stream URLs.

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
SCREENLOOP_BOOTSTRAP_PASSWORD=dev-password-please-change SCREENLOOP_SECRET_KEY=dev-secret-change-me python -m screenloop
```

Run checks:

```bash
python3 -m py_compile dlna_push.py screenloop/*.py tests/test_core.py
python3 -m unittest discover -s tests
```

## Release Flow

Development is staged through `dev`. Test changes there first and use the `ghcr.io/gezzydax/screenloop:dev` image for integration checks. Merge `dev` into `main` through a pull request when ready.

`main` is protected and publishes the `main` image tag for release candidates. Release Please uses Conventional Commits on `main` to open release PRs; merging a release PR creates the GitHub release and publishes versioned GHCR tags such as `0.1.0` plus `latest`.

## Legacy CLI

`dlna_push.py` is deprecated and kept temporarily as a fallback for direct one-off DLNA pushes. The web daemon is the supported interface and the CLI is planned for removal or archival after the daemon stabilizes.
