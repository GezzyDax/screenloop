# Screenloop

Screenloop is a lightweight self-hosted control panel for playing managed video playlists on local TVs and signage screens.

It is being built as a modern open-source alternative to the aging Home Media Server workflow: upload videos once, let Screenloop prepare TV-safe copies, assign playlists to Samsung/LG/DLNA TVs, and monitor playback from a secured web panel.

## Why

Many offices, clinics, shops, and homelabs still run ad-hoc media servers, USB sticks, or old DLNA tools to show videos on TVs. That usually means manual file conversion, unclear TV status, no playlist control, and weak access control.

Screenloop solves that by combining:

- Local-first TV playback over DLNA/UPnP.
- Per-TV playlists and profiles for Samsung, LG, and generic DLNA renderers.
- Automatic MP4/H.264/AAC preparation for TV compatibility.
- A web control panel with users, roles, CSRF protection, audit events, and signed stream URLs.
- Docker/GHCR deployment for small LAN and corporate environments.

## What Works Today

- Upload videos and transcode them into TV-safe MP4 files.
- Create ordered playlists and loop them automatically.
- Configure multiple TVs with different profiles and playlists.
- Scan the LAN for DLNA MediaRenderer devices.
- Monitor TV reachability, DLNA/SOAP readiness, current media, and next media.
- Control playback: skip/play next, stop, restart playlist, rediscover.
- Use `/api/v1` for future Vue UI and integrations.

## Quick Start

### Install latest stable build

```bash
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/install.sh -o /tmp/screenloop-install.sh && bash /tmp/screenloop-install.sh'
```

Open:

```text
http://<server-ip>:8099
```

The installer asks for the HTTP port, bootstrap admin credentials, and advertised network interfaces.
If Docker or the Docker Compose plugin is missing, it asks before installing them.

### Install latest dev build

Use this when testing unreleased features:

```bash
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/dev/install.sh -o /tmp/screenloop-install.sh && bash /tmp/screenloop-install.sh --dev'
```

If installing to `/opt/screenloop` without root, the installer re-runs itself with `sudo` and prompts for your sudo password. If your environment blocks that, run the same command with explicit sudo:

```bash
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/dev/install.sh -o /tmp/screenloop-install.sh && sudo bash /tmp/screenloop-install.sh --dev'
```

## Docker Compose

### Run from source

```bash
git clone https://github.com/GezzyDax/screenloop.git
cd screenloop
cp .env.example .env
# edit SCREENLOOP_BOOTSTRAP_PASSWORD and SCREENLOOP_SECRET_KEY
docker compose up --build -d
```

### Run stable GHCR image

```bash
mkdir -p screenloop && cd screenloop
curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/docker-compose.ghcr.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/.env.example -o .env
# edit .env
docker compose up -d
```

### Run dev GHCR image

```bash
mkdir -p screenloop && cd screenloop
curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/dev/docker-compose.ghcr.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/dev/.env.example -o .env
printf "\nSCREENLOOP_IMAGE='ghcr.io/gezzydax/screenloop:dev'\n" >> .env
# edit .env
docker compose up -d
```

`network_mode: host` is intentional. SSDP discovery and TV access to local stream URLs are much more reliable on the host network.

## Updates

### Update stable install

```bash
cd /opt/screenloop
./update.sh
```

Or fetch the latest stable updater:

```bash
cd /opt/screenloop
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/update.sh -o /tmp/screenloop-update.sh && bash /tmp/screenloop-update.sh'
```

### Update to dev build

```bash
cd /opt/screenloop
./update.sh -dev
```

Or fetch the latest dev updater:

```bash
cd /opt/screenloop
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/dev/update.sh -o /tmp/screenloop-update.sh && bash /tmp/screenloop-update.sh -dev'
```

### Switch back to stable

```bash
cd /opt/screenloop
./update.sh --main
```

## See A Result In 5 Minutes

1. Install Screenloop and open the web panel.
2. Upload one short `.mp4`, `.mkv`, or `.avi` video on the Media page.
3. Wait until transcode status becomes `done`/`ready`.
4. Create a playlist and add the video.
5. Add or scan a TV, assign the playlist, and click `Skip / Play next`.

The TV should request a signed `/stream/...` URL from Screenloop and start playback.

## Configuration

Important environment variables:

- `SCREENLOOP_BOOTSTRAP_USER` / `SCREENLOOP_BOOTSTRAP_PASSWORD` - first admin account created when the user table is empty.
- `SCREENLOOP_SECRET_KEY` - required for CSRF and signed stream URLs.
- `SCREENLOOP_HTTP_PORT` - web UI and media stream port, default `8099`.
- `SCREENLOOP_ADVERTISE_HOSTS` - comma-separated local IPs advertised to TVs for multi-subnet hosts, for example `192.0.2.10,198.51.100.10`.
- `SCREENLOOP_ALLOWED_TV_CIDRS` - optional TV network allowlist, for example `192.0.2.0/24,198.51.100.0/24`.
- `SCREENLOOP_TRUSTED_PROXY_CIDRS` - reverse proxy IP ranges allowed to supply `X-Forwarded-For`.
- `SCREENLOOP_COOKIE_SECURE` - set to `true` when serving through HTTPS.
- `SCREENLOOP_MAX_UPLOAD_BYTES` - upload limit, default 2 GiB.
- `SCREENLOOP_ACCESS_LOG` - set to `false` to reduce HTTP access log noise.

Legacy `GEZZDLNA_*` variables still work as deprecated fallbacks. New deployments should use `SCREENLOOP_*`.

## Security

Screenloop is designed for trusted LAN use. Do not expose it directly to the public Internet.

Current baseline:

- Local users with roles: `admin`, `operator`, `viewer`.
- HttpOnly cookie sessions.
- CSRF protection for unsafe web/API actions.
- Login, upload, stream-token, and TV-command rate limits.
- Signed media stream URLs.
- Audit events for login, upload, user, playlist, TV, and command actions.
- Optional TV subnet allowlist.

For remote access, put Screenloop behind a reverse proxy with TLS, strong authentication, and network restrictions.

## API

Screenloop exposes a JSON API under `/api/v1` for the future Vue UI and integrations.

- `POST /api/v1/auth/login` returns the current user and a `csrf_token`.
- `GET /api/v1/session` returns the current user, roles, and a fresh `csrf_token`.
- Unsafe API methods require `X-CSRF-Token`.
- `GET /api/v1/status` returns the live dashboard payload for polling.

See [docs/API.md](docs/API.md) for the API security model, endpoint groups, frontend rules, and OpenAPI entrypoints.

Interactive docs are available at `/docs`, `/redoc`, and `/openapi.json`.

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
SCREENLOOP_BOOTSTRAP_PASSWORD=dev-password-please-change \
SCREENLOOP_SECRET_KEY=dev-secret-change-me \
python -m screenloop
```

Run checks:

```bash
python3 -m py_compile dlna_push.py screenloop/*.py tests/*.py
python3 -m unittest discover -s tests
docker compose build
```

## Release Flow

Development is staged through `dev`. Test changes there first and use `ghcr.io/gezzydax/screenloop:dev` for integration checks.

`main` is protected and publishes the `main` image tag. Versioned GitHub releases publish semver GHCR tags such as `0.3.0` plus `latest`.

Release Please uses Conventional Commits merged into `main`:

- `fix:` creates a patch release.
- `feat:` creates a minor release.
- `feat!:` or `BREAKING CHANGE:` creates a major release.

## Roadmap

Screenloop is planned as a staged replacement for legacy Home Media Server-style workflows, not just a DLNA file server.

- `v0.x`: reliable single-node LAN control panel with secure users, playlists, TV profiles, API, installer, updates, and GHCR images.
- `v1.0`: stable `/api/v1` contract and a dedicated Vue/Vite web UI with a stronger product identity.
- `v1.x`: headless/CLI edition for automation and server-only deployments, for example `screenloopctl upload`, `screenloopctl playlist assign`, `screenloopctl tv command`.
- `v1.x`: better TV profile capabilities: model-specific bitrate, resolution, audio, DLNA headers, and replay strategies.
- `v1.x`: full backup/restore for TVs, playlists, media metadata, users, and settings.
- `v2.0`: node-based cluster mode for multiple networks or locations.
- `v2.0`: central controller with lightweight nodes/agents that discover local TVs, cache prepared media, and execute commands inside their LAN.
- `v2.0`: secure outbound node connection model, so remote sites do not need inbound port forwarding.
- Ongoing: diagnostics, worker health, cache size, build version, audit views, reverse proxy examples, screenshots, and demo GIFs.

## Community

Issues and pull requests are welcome. Useful contributions include:

- Real TV compatibility reports.
- Profile tuning for Samsung/LG models.
- Docker, reverse proxy, and deployment examples.
- Documentation and screenshots/GIF demos.
- Security review and API contract tests.

## Legacy CLI

`dlna_push.py` is deprecated and kept temporarily as a fallback for direct one-off DLNA pushes. The web daemon is the supported interface and the CLI is planned for removal or archival after the daemon stabilizes.
