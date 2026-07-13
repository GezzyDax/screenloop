# Screenloop

**English** | [Русский](README.ru.md)

Screenloop is a lightweight self-hosted control panel for playing managed video playlists on local TVs and signage screens.

It is a modern open-source alternative to the aging Home Media Server workflow: upload videos once, let Screenloop prepare TV-safe copies, assign playlists to Samsung/LG/DLNA TVs, and monitor playback from a secured web panel. With node mode, one panel can also drive TVs in remote networks — branch offices, other floors, other sites — without inbound ports at the remote side.

## Why

Many offices, clinics, shops, and homelabs still run ad-hoc media servers, USB sticks, or old DLNA tools to show videos on TVs. That usually means manual file conversion, unclear TV status, no playlist control, and weak access control.

Screenloop solves that by combining:

- Local-first TV playback over DLNA/UPnP.
- Per-TV playlists and profiles for Samsung, LG, and generic DLNA renderers.
- Automatic MP4/H.264/AAC preparation for TV compatibility.
- A web control panel with users, roles, CSRF protection, audit events, and signed stream URLs.
- Remote-site nodes that connect outbound to the central controller.
- Docker/GHCR deployment (amd64 and arm64) for small LAN and corporate environments.

## What Works Today

- Upload videos with progress and duplicate detection; transcode them into TV-safe MP4 files per TV profile.
- Create ordered playlists (drag-and-drop reordering) and loop them automatically.
- Configure multiple TVs with different profiles and playlists; scan the LAN for DLNA MediaRenderer devices.
- Monitor TV reachability, DLNA/SOAP readiness, current and next media, playback progress.
- Control playback: skip/play next, stop, restart playlist, mute, rediscover.
- Manage remote sites with nodes: outbound-only connection, local media cache, offline autoplay ([docs/nodes.md](docs/nodes.md)).
- Local users with roles (`viewer` < `operator` < `admin`), self-service password change, session management, security audit log.
- Localized UI (English/Russian) with light and dark themes.
- Use `/api/v1` for the Vue UI and integrations.

## Quick Start

### Install latest stable build

```bash
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/install.sh -o /tmp/screenloop-install.sh && bash /tmp/screenloop-install.sh'
```

Open:

```text
http://<server-ip>:8098
```

The installer asks for the backend HTTP port, frontend UI port, bootstrap admin credentials, and advertised network interfaces.
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

### Install a remote node

On a host in the remote network, after creating an enrollment token in the panel (**Nodes → Create node**):

```bash
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/install.sh -o /tmp/screenloop-install.sh && bash /tmp/screenloop-install.sh --node http://<controller-ip>:8099'
```

See [docs/nodes.md](docs/nodes.md) for the architecture and details.

## Docker Compose

### Run from source

```bash
git clone https://github.com/GezzyDax/screenloop.git
cd screenloop
cp .env.example .env
# set SCREENLOOP_BOOTSTRAP_PASSWORD and SCREENLOOP_SECRET_KEY (openssl rand -hex 32)
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
Docker Compose runs two containers: `screenloop` for backend/API/DLNA work and `screenloop-ui` for the Vue frontend. A third image, `screenloop-node`, is a lightweight agent for remote sites. Images are published for amd64 and arm64.

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

### Switch back to stable

```bash
cd /opt/screenloop
./update.sh --main
```

### Roll back to a released version

```bash
cd /opt/screenloop
./update.sh --rollback 1.5.0
```

This pins both images to the given release and restarts; the data volume is untouched.

## See A Result In 5 Minutes

1. Install Screenloop and open the web panel.
2. Upload one short `.mp4`, `.mkv`, or `.avi` video on the Media page.
3. Wait until the transcode status becomes ready.
4. Create a playlist and add the video.
5. Add or scan a TV, assign the playlist, and click `Play next`.

The TV should request a signed `/stream/...` URL from Screenloop and start playback.

## Configuration

Important environment variables:

- `SCREENLOOP_BOOTSTRAP_USER` / `SCREENLOOP_BOOTSTRAP_PASSWORD` - first admin account created when the user table is empty. Remove the password from `.env` after the first login.
- `SCREENLOOP_SECRET_KEY` - required for CSRF and signed stream URLs. Generate with `openssl rand -hex 32`; placeholder values are rejected at startup.
- `SCREENLOOP_HTTP_PORT` - backend API and media stream port, default `8099`.
- `SCREENLOOP_UI_PORT` - Vue frontend port, default `8098`.
- `SCREENLOOP_ADVERTISE_HOSTS` - comma-separated local IPs advertised to TVs for multi-subnet hosts, for example `192.0.2.10,198.51.100.10`.
- `SCREENLOOP_ALLOWED_TV_CIDRS` - optional TV network allowlist, for example `192.0.2.0/24,198.51.100.0/24`.
- `SCREENLOOP_TRUSTED_PROXY_CIDRS` - reverse proxy IP ranges allowed to supply `X-Forwarded-For`.
- `SCREENLOOP_COOKIE_SECURE` - set to `true` when serving through HTTPS.
- `SCREENLOOP_SESSION_MAX_LIFETIME_SECONDS` - absolute session lifetime cap for sliding renewal, default 30 days.
- `SCREENLOOP_MAX_UPLOAD_BYTES` - upload limit, default 2 GiB, enforced while the file is being received and by the UI proxy.
- `SCREENLOOP_MIN_FREE_DISK_BYTES` - refuse uploads when free disk space drops below this, default 1 GiB.
- `SCREENLOOP_STREAM_TOKEN_TTL_SECONDS` - lifetime of signed stream URLs, default 6 hours. Tokens are bound to the TV address.
- `SCREENLOOP_TRANSCODE_TIMEOUT_SECONDS` - hard ffmpeg timeout per transcode job, default 2 hours.
- `SCREENLOOP_FFPROBE_TIMEOUT_SECONDS` - ffprobe timeout for uploads and duration checks, default 30.
- `SCREENLOOP_ACCESS_LOG` - set to `false` to reduce HTTP access log noise.
- `SCREENLOOP_LOG_LEVEL` - application log level, default `INFO`.
- `SCREENLOOP_API_DOCS` - set to `false` to disable `/docs`, `/redoc`, and `/openapi.json` in production.
- `SCREENLOOP_UPDATE_CHECK` - opt-in GitHub release check shown in the panel, default `false`.
- `SCREENLOOP_POLL_LOOP_INTERVAL` - worker loop interval in seconds, default `1`.
- `SCREENLOOP_PING_POLL` - fast host reachability check interval in seconds, default `2`.
- `SCREENLOOP_OFFLINE_POLL` - DLNA rediscovery interval for reachable but not ready TVs, default `3`.
- `SCREENLOOP_ONLINE_POLL` - full DLNA/SOAP status interval for online TVs, default `5`.
- `SCREENLOOP_SSDP_TIMEOUT` - per SSDP discovery target timeout in seconds, default `2`.
- `SCREENLOOP_SOAP_TIMEOUT` - timeout for UPnP/DLNA control calls, default `20` seconds.
- `SCREENLOOP_SOAP_NEXT_TIMEOUT` - short timeout for optional next-item preload calls, default `3` seconds.
- `SCREENLOOP_PRELOAD_NEXT_URI` - best-effort `SetNextAVTransportURI` preload for TVs that support it, default `true`.
- `SCREENLOOP_AUTO_ADVANCE_END_GRACE` - extra seconds after known media duration before Screenloop pushes the next playlist item when a TV keeps reporting `PLAYING`, default `5`.

Node agent variables (`SCREENLOOP_NODE_*`) are documented in [docs/nodes.md](docs/nodes.md).

Legacy `GEZZDLNA_*` variables still work as deprecated fallbacks. New deployments should use `SCREENLOOP_*`.

## Security

Screenloop is designed for trusted LAN use. Do not expose it directly to the public Internet.

Current baseline:

- Startup refuses placeholder or publicly documented secrets.
- Local users with roles `viewer` < `operator` < `admin`; the last active admin cannot be demoted or disabled.
- HttpOnly cookie sessions with sliding renewal and an absolute lifetime cap; users can list and revoke their own sessions.
- CSRF protection for unsafe web/API actions.
- Login rate limits per IP and per username; upload, stream-token, and TV-command rate limits.
- Signed media stream URLs bound to the TV address with a configurable lifetime.
- Security audit events retained separately from the service event stream and hidden from the viewer role.
- Optional TV subnet allowlist; TV control URLs are validated against it.
- Node access uses one-time enrollment tokens and hashed permanent tokens; revocation is immediate.

For remote access, put Screenloop behind a reverse proxy with TLS, strong authentication, and network restrictions.

Production guides:

- [docs/deployment.md](docs/deployment.md) - architecture, ports, reverse proxy with TLS, update and rollback flow.
- [docs/hardening.md](docs/hardening.md) - production hardening checklist (firewalling the backend port, secrets, roles).
- [docs/backup.md](docs/backup.md) - backup and restore of the data volume.
- [docs/nodes.md](docs/nodes.md) - remote-site nodes: architecture, setup, security model.

## API

Screenloop exposes a JSON API under `/api/v1` for the Vue UI and integrations.

- `POST /api/v1/auth/login` returns the current user and a `csrf_token`.
- `GET /api/v1/session` returns the current user, roles, and a fresh `csrf_token`.
- Unsafe API methods require `X-CSRF-Token`.
- `GET /api/v1/status` returns the live dashboard payload for polling; `GET /api/v1/stream/events` streams it over SSE.
- `GET /api/v1/version` returns build version, revision, author, repository, and optional update state.
- `GET /api/v1/diagnostics` returns admin-only runtime diagnostics without secrets.

See [docs/API.md](docs/API.md) for the API security model, endpoint groups, frontend rules, and OpenAPI entrypoints.

Interactive docs are available at `/docs`, `/redoc`, and `/openapi.json` (disable in production with `SCREENLOOP_API_DOCS=false`).

## Data

Docker stores data in the `screenloop-data` volume:

- `/data/db/screenloop.sqlite3` - SQLite state.
- `/data/media` - uploaded originals.
- `/data/transcoded` - TV-safe MP4 copies.

Backup and restore: [docs/backup.md](docs/backup.md).

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export SCREENLOOP_SECRET_KEY="$(openssl rand -hex 32)"
export SCREENLOOP_BOOTSTRAP_PASSWORD="dev-$(openssl rand -hex 4)"
echo "bootstrap admin password: $SCREENLOOP_BOOTSTRAP_PASSWORD"
python -m screenloop
```

Run checks (CI runs the same):

```bash
python3 -m ruff check screenloop tests
python3 -m mypy screenloop
python3 -m unittest discover -s tests
docker compose build
```

Frontend dev server (proxies `/api` and `/stream` to `127.0.0.1:8099`):

```bash
cd frontend
npm install
npm run dev
```

## Release Flow

Development is staged through `dev`. Test changes there first and use `ghcr.io/gezzydax/screenloop:dev` for integration checks.

`main` is protected and publishes the `main` image tag. Versioned GitHub releases publish semver GHCR tags such as `1.5.0`, `1.5`, and `latest`. Images are only published after lint, type checks, and tests pass.

Release Please uses Conventional Commits merged into `main`:

- `fix:` creates a patch release.
- `feat:` creates a minor release.
- `feat!:` or `BREAKING CHANGE:` creates a major release.

If Release Please PR checks stay pending, configure a `RELEASE_PLEASE_TOKEN` repository secret with a fine-scoped PAT that can create pull requests. PRs created by the default `GITHUB_TOKEN` may not trigger required checks.

## Roadmap

Done:

- Single-server LAN control panel with secure users, playlists, TV profiles, API, installer, updates, and GHCR images.
- Diagnostics page with storage, worker, network, ffmpeg/docker, and safe config checks.
- Stable `/api/v1` contract and Vue/Vite as the only supported web UI, with dark theme and RU/EN localization.
- Node-based cluster mode: central controller with lightweight outbound-only nodes that discover local TVs, cache prepared media, and keep playing while offline.
- CI with lint/type checks, dependency and image vulnerability scanning, multi-arch builds, gated publishing.

Planned:

- Headless/CLI edition for automation, for example `screenloopctl upload`, `screenloopctl playlist assign`.
- Model-specific TV profile tuning: bitrate, resolution, audio, DLNA headers, replay strategies.
- Scheduled playlists (dayparting) and per-TV schedules.
- Screenshots and demo GIFs in this README.

## Community

Issues and pull requests are welcome. Useful contributions include:

- Real TV compatibility reports.
- Profile tuning for Samsung/LG models.
- Docker, reverse proxy, and deployment examples.
- Documentation and screenshots/GIF demos.
- Security review and API contract tests.

## Legacy CLI

The deprecated `dlna_push.py` standalone CLI has been removed. The web daemon and `/api/v1` are the supported interfaces; the last CLI version is available in the git history of releases up to 1.5.x.

## Upgrading to 2.0

Screenloop 2.0 removes the legacy server-rendered web panel and the `dlna_push.py` CLI in favor of the `/api/v1` REST API and the Vue-based UI, and introduces node mode for multi-network deployments. If you operate the standalone CLI or scripts against the old template-rendered pages, update them to use `/api/v1` (see [docs/API.md](docs/API.md)) or the current UI before upgrading past 1.5.x.
