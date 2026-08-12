# Screenloop

[Русский](README.md) | **English**

[![CI](https://github.com/GezzyDax/screenloop/actions/workflows/ci.yml/badge.svg)](https://github.com/GezzyDax/screenloop/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/GezzyDax/screenloop)](https://github.com/GezzyDax/screenloop/releases)
[![GHCR](https://img.shields.io/badge/GHCR-screenloop-2496ED?logo=docker&logoColor=white)](https://github.com/GezzyDax/screenloop/pkgs/container/screenloop)

**Video on the TVs in your network, on a playlist, without USB sticks.**

Screenloop takes your clips, prepares copies your TV will actually play, and loops playlists onto screens over DLNA. Everything is visible and controllable from a web panel: what is playing, what is next, which screen dropped off.

It runs inside your local network. One panel also drives remote sites — branch offices, other floors — through nodes that need no inbound ports.

---

## Who it is for

Offices, clinics, shops, factories, homelabs — anywhere clips play on screens and it is still done with USB sticks, an ad-hoc media server, or old DLNA tools. Manual conversion per TV, no idea which screens are alive, no access control: that is exactly what Screenloop replaces.

## What it does

| Problem | How it is solved |
|---|---|
| The TV refuses to play the file | Automatic transcode to MP4/H.264/AAC for that TV's profile |
| Different clip on each screen | Per-TV playlist and per-TV profile |
| No idea what the screens are doing | Live monitoring: reachability, DLNA readiness, current and next item, progress |
| A clip is stuck or needs switching | Panel commands: play next, stop, restart playlist, mute, rediscover |
| TVs are on another network | Nodes: connect outbound to the panel, cache media, keep playing when the link drops |
| The TV is not on the supported list | Templates: describe the model in a `.toml` — no code change, no waiting for a release |
| Access needs to be restricted | Roles `viewer` < `operator` < `admin`, audit log, signed media URLs |
| Screens run around the clock and burn out | Operating hours: outside its window Screenloop sends nothing, and a TV switched off with the remote is no longer switched back on |

Also: LAN scan for DLNA renderers, drag-and-drop playlist ordering, duplicate detection on upload, dark theme, English and Russian UI, and a `/api/v1` JSON API for integrations.

---

## Quick start

Install on a server in your network with one command:

```bash
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/install.sh -o /tmp/screenloop-install.sh && bash /tmp/screenloop-install.sh'
```

The installer asks for ports, the first administrator's credentials, and which network interfaces TVs will fetch video from. If Docker or the Compose plugin is missing, it offers to install them.

Then open `http://<server-ip>:8098` and get a picture on screen in five steps:

1. Upload a short video (`.mp4`, `.mkv`, `.avi`) on the **Media** page.
2. Wait for the "ready" status — Screenloop transcodes it for your TVs.
3. Create a playlist and add the clip.
4. On the **TVs** page, scan the network or add a TV by IP.
5. Assign the playlist and click **Play next**.

The TV requests a signed `/stream/...` URL from Screenloop and starts playing.

<details>
<summary><b>Other install options</b></summary>

### Dev build

For testing unreleased changes:

```bash
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/dev/install.sh -o /tmp/screenloop-install.sh && bash /tmp/screenloop-install.sh --dev'
```

Installing to `/opt/screenloop` needs root. The installer re-runs itself with `sudo`; if your environment blocks that, use explicit sudo:

```bash
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/dev/install.sh -o /tmp/screenloop-install.sh && sudo bash /tmp/screenloop-install.sh --dev'
```

### Remote node

Create an enrollment token in the panel first (**Nodes → Create node**), then on a host in the remote network:

```bash
sh -c 'curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/install.sh -o /tmp/screenloop-install.sh && bash /tmp/screenloop-install.sh --node http://<controller-ip>:8099'
```

Architecture and security model: [docs/nodes.md](docs/nodes.md).
If a node is deleted and recreated, replace the one-time token in `.env` and
recreate the container. Current agents replace the revoked `/data/node.token`
automatically without deleting the volume or media cache.

### Docker Compose by hand

Stable GHCR image:

```bash
mkdir -p screenloop && cd screenloop
curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/docker-compose.ghcr.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/GezzyDax/screenloop/main/.env.example -o .env
# set SCREENLOOP_SECRET_KEY and SCREENLOOP_BOOTSTRAP_PASSWORD
docker compose up -d
```

From source:

```bash
git clone https://github.com/GezzyDax/screenloop.git
cd screenloop
cp .env.example .env
# set SCREENLOOP_BOOTSTRAP_PASSWORD and SCREENLOOP_SECRET_KEY (openssl rand -hex 32)
docker compose up --build -d
```

Two containers come up: `screenloop` (backend, API, DLNA) and `screenloop-ui` (web panel). A third image, `screenloop-node`, is the remote-site agent. Built for amd64 and arm64.

`network_mode: host` is deliberate — SSDP discovery and TV access to stream URLs are noticeably more reliable on the host network.

</details>

## Updating and rolling back

```bash
cd /opt/screenloop
./update.sh                  # to the latest stable
./update.sh -dev             # to the dev build
./update.sh --main           # back to stable
./update.sh --rollback 1.5.0 # to a specific release
```

A rollback pins both images to that version and restarts. The data volume is untouched.

---

## TV templates

There are hundreds of DLNA renderers, each with its own ceilings for bitrate, resolution, and H.264 profile. The maintainers cannot test them all — the only person with your TV is you.

So a TV profile is a plain `.toml` file, not code. Adding your model needs no rebuild:

- **By hand** — drop the file into `<data_dir>/profiles/` or upload it via **Templates → Add a template** in the panel. It works immediately, no restart.
- **From the community catalog** — set `SCREENLOOP_COMMUNITY_CATALOG_CHECK=true` and templates contributed by other users show up in the panel. Off by default: without the flag Screenloop makes no outbound request at all.

Format, full field list, and how to work out settings for your TV: [docs/tv-templates.md](docs/tv-templates.md).

Five templates ship in the box: generic DLNA, LG webOS, LG NetCast, Samsung Tizen, Samsung Legacy.

---

## Operating hours

DLNA has no power command. Worse, the UPnP spec requires a renderer to leave standby to service `Play` — so a TV that is being pushed to switches itself back on, however many times somebody turns it off with the remote.

That leaves exactly one lever: send it nothing.

- **The schedule.** Set the site-wide days and hours in Settings; outside that window Screenloop sends one `Stop` and then leaves the screen alone. Off by default — an upgrade must not start blanking screens nobody asked about. A group can set hours for a whole site, floor, or zone, while an individual TV can override them or run continuously. Precedence is **TV → nearest group with its own mode → ancestor groups → site schedule**. Moving a group immediately changes the inherited window for every nested screen, including TVs on remote nodes.
- **Manual power-off.** When a TV reports `NO_MEDIA_PRESENT` for several consecutive polls while it still has media assigned, somebody switched it off at the screen: Samsung and LG clear the AVTransport instance in standby. Screenloop suspends playback and does not wake the panel until the next window opens or an operator presses Resume.

Set the timezone with `SCREENLOOP_TIMEZONE` — a schedule is read off a wall clock, and containers run on UTC unless told otherwise.

## Configuration

These are usually all you need; everything else has sensible defaults:

| Variable | What for |
|---|---|
| `SCREENLOOP_SECRET_KEY` | Required. Signs CSRF tokens and media URLs: `openssl rand -hex 32` |
| `SCREENLOOP_BOOTSTRAP_USER` / `SCREENLOOP_BOOTSTRAP_PASSWORD` | First administrator. Remove the password from `.env` after logging in |
| `SCREENLOOP_HTTP_PORT` / `SCREENLOOP_UI_PORT` | Backend (`8099`) and panel (`8098`) ports |
| `SCREENLOOP_ADVERTISE_HOSTS` | Server IPs advertised to TVs — needed on multi-subnet hosts |
| `SCREENLOOP_ALLOWED_TV_CIDRS` | Restrict which networks Screenloop talks to at all |
| `SCREENLOOP_COOKIE_SECURE` | `true` when the panel is behind HTTPS |
| `SCREENLOOP_MAX_UPLOAD_BYTES` | Upload limit, 2 GiB by default |

Full reference of every variable: [docs/configuration.md](docs/configuration.md).

## Security

Screenloop is built for a trusted local network. **Do not expose it directly to the Internet** — for remote access put a reverse proxy with TLS and network restrictions in front of it.

- The app refuses to start on an empty, short, or placeholder secret.
- HttpOnly cookie sessions, CSRF on every unsafe action, rate limits on login, uploads, and TV commands.
- Media URLs are signed, bound to the TV's address, and expire.
- Roles `viewer` < `operator` < `admin`; the last active administrator cannot be disabled.
- A separate security audit log, hidden from the viewer role.
- Nodes join with one-time enrollment tokens, permanent tokens are stored hashed, revocation is immediate.

More: [deployment](docs/deployment.md) · [hardening checklist](docs/hardening.md) · [backups](docs/backup.md) · [nodes](docs/nodes.md)

## Data

Docker keeps everything in the `screenloop-data` volume:

- `/data/db/screenloop.sqlite3` — state.
- `/data/media` — uploaded originals.
- `/data/transcoded` — transcoded copies.
- `/data/profiles` — custom TV templates.

Backup and restore: [docs/backup.md](docs/backup.md).

## API

The `/api/v1` JSON API is the same one the panel uses. Unsafe methods require an `X-CSRF-Token` header.

- `POST /api/v1/auth/login` — sign in, returns the user and a `csrf_token`.
- `GET /api/v1/status` — dashboard state; `GET /api/v1/stream/events` — the same over SSE.
- `GET /api/v1/profiles` — installed TV templates.
- `GET /api/v1/diagnostics` — admin-only diagnostics without secrets.

Full contract, role matrix, and frontend rules: [docs/API.md](docs/API.md). Interactive docs at `/docs`, `/redoc`, `/openapi.json` (disable with `SCREENLOOP_API_DOCS=false`).

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

Frontend separately (proxies `/api` and `/stream` to `127.0.0.1:8099`):

```bash
cd frontend && npm install && npm run dev
```

Pre-PR checks, the same ones CI runs:

```bash
python3 -m ruff check screenloop tests scripts
python3 -m mypy screenloop
python3 -m unittest discover -s tests
docker compose build
./scripts/smoke.sh all   # boots the images and exercises the whole API
```

Work is integrated on `dev` and released from `main`: push a `feat/…` or `fix/…` branch, open a pull request into `dev`, merge it when CI is green. `ghcr.io/gezzydax/screenloop:dev` is rebuilt from every commit on `dev` — that is the image to run on a staging screen.

When the staging build holds up, open a pull request from `dev` into `main` and rebase-merge it. That merge is the release gate: Release Please turns it into a version from the Conventional Commits it contains (`fix:` → patch, `feat:` → minor, `feat!:` or `BREAKING CHANGE:` → major), and the tag, the GitHub release, `latest`, and the versioned GHCR tags follow automatically. `dev` is rebased back onto `main` by a workflow, so there is no manual resync. See [CONTRIBUTING.md](CONTRIBUTING.md).

## What is next

- Headless/CLI edition for automation: `screenloopctl upload`, `screenloopctl playlist assign`.
- Scheduled playlists (dayparting).
- Screenshots and a demo in this README.

## Contributing

Issues and pull requests are welcome. The most useful ones:

- **Templates for real TVs** — the single most valuable contribution. Nobody else has your model.
- Compatibility reports: what worked, what did not, on which firmware.
- Docker, reverse proxy, and deployment examples.
- Screenshots, demos, documentation.
- Security review and API contract tests.

## Legacy CLI

The standalone `dlna_push.py` utility has been removed. The web panel and `/api/v1` are the supported interfaces; the last CLI version remains in git history up to release 1.5.x.
