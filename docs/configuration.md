# Configuration

**English** | [Русский](configuration.ru.md)

Everything is configured through `SCREENLOOP_`-prefixed environment variables. In a Docker Compose install they live in the `.env` file next to `docker-compose.yml`; see [.env.example](../.env.example) for a template.

Legacy `GEZZDLNA_*` variables still work as deprecated fallbacks, but new installs should use `SCREENLOOP_*`.

## Required

| Variable | Default | What it does |
|---|---|---|
| `SCREENLOOP_SECRET_KEY` | — | Signing key for CSRF tokens and stream URLs. Generate with `openssl rand -hex 32`. The app refuses to start on an empty, short (< 16 characters), or placeholder value. |
| `SCREENLOOP_BOOTSTRAP_USER` | `admin` | Username of the first administrator. |
| `SCREENLOOP_BOOTSTRAP_PASSWORD` | — | Password for that account. It is only created while the user table is empty. Remove the variable from `.env` after the first login. |

## Network

| Variable | Default | What it does |
|---|---|---|
| `SCREENLOOP_HTTP_HOST` | `0.0.0.0` | Address the backend listens on. |
| `SCREENLOOP_HTTP_PORT` | `8099` | Backend API and media streaming port. |
| `SCREENLOOP_UI_PORT` | `8098` | Web panel port. |
| `SCREENLOOP_ADVERTISE_HOSTS` | auto-detected | Comma-separated server IPs advertised to TVs. Needed when the host sits on several subnets. |
| `SCREENLOOP_ADVERTISE_HOST` | — | Single-address form, kept for compatibility. |
| `SCREENLOOP_PUBLIC_URL` | — | Public origin when Screenloop is behind a reverse proxy. |
| `SCREENLOOP_TRUSTED_PROXY_CIDRS` | `127.0.0.1/32,::1/128` | Ranges allowed to supply `X-Forwarded-For`. Anything else is ignored so a client cannot spoof its own IP. |
| `SCREENLOOP_ALLOWED_TV_CIDRS` | empty | TV network allowlist, for example `192.0.2.0/24,198.51.100.0/24`. Empty means any address is allowed. |

## Storage

| Variable | Default | What it does |
|---|---|---|
| `SCREENLOOP_DATA_DIR` | `~/.local/share/screenloop`, `/data` in Docker | Runtime data root. |
| `SCREENLOOP_DB_PATH` | `<data_dir>/db/screenloop.sqlite3` | SQLite database file. |
| `SCREENLOOP_MEDIA_DIR` | `<data_dir>/media` | Uploaded originals. |
| `SCREENLOOP_TRANSCODE_DIR` | `<data_dir>/transcoded` | TV-safe MP4 copies. |
| `SCREENLOOP_PROFILES_DIR` | `<data_dir>/profiles` | Custom and community-installed TV templates. |
| `SCREENLOOP_MAX_UPLOAD_BYTES` | `2147483648` (2 GiB) | Upload size limit, enforced while the file is being received and by the panel's nginx proxy. |
| `SCREENLOOP_MIN_FREE_DISK_BYTES` | `1073741824` (1 GiB) | Refuse uploads when free disk space drops below this. |

## Security and sessions

| Variable | Default | What it does |
|---|---|---|
| `SCREENLOOP_COOKIE_SECURE` | `false` | Set to `true` when serving the panel over HTTPS. |
| `SCREENLOOP_SESSION_TTL_SECONDS` | `43200` (12 h) | Session lifetime with sliding renewal. |
| `SCREENLOOP_SESSION_MAX_LIFETIME_SECONDS` | `2592000` (30 days) | Absolute cap: a re-login is required after this regardless of activity. |
| `SCREENLOOP_STREAM_TOKEN_TTL_SECONDS` | `21600` (6 h) | Lifetime of signed stream URLs. Tokens are bound to the TV's address. |
| `SCREENLOOP_API_DOCS` | `true` | `false` disables `/docs`, `/redoc`, and `/openapi.json`. |
| `SCREENLOOP_ALLOW_INSECURE_AUTH` | `false` | Drops the startup secret checks. **Local testing only**, never in production. |

## Logging and updates

| Variable | Default | What it does |
|---|---|---|
| `SCREENLOOP_LOG_LEVEL` | `INFO` | Application log level. |
| `SCREENLOOP_ACCESS_LOG` | `true` | `false` quiets HTTP access logs. |
| `SCREENLOOP_UPDATE_CHECK` | `false` | Checks GitHub for new releases and shows the result in the panel footer. This is the only routine outbound request Screenloop makes, and it is off by default. |
| `SCREENLOOP_UPDATE_CHECK_URL` | GitHub Releases API | Where to read release information from. |
| `SCREENLOOP_UPDATE_CHECK_INTERVAL_SECONDS` | `21600` (6 h) | How often to re-check. |

## TV template catalog

| Variable | Default | What it does |
|---|---|---|
| `SCREENLOOP_COMMUNITY_CATALOG_CHECK` | `false` | Lets the panel fetch the community template catalog. While off, no outbound request is made at all. Import by URL and file upload work regardless of this flag. |
| `SCREENLOOP_COMMUNITY_CATALOG_URL` | `index.json` of the screenloop-templates repo | Catalog index location. |
| `SCREENLOOP_COMMUNITY_CATALOG_CACHE_SECONDS` | `3600` (1 h) | How long the index stays cached. |

The template format is documented in [tv-templates.md](tv-templates.md).

## Transcoding

| Variable | Default | What it does |
|---|---|---|
| `SCREENLOOP_TRANSCODE_TIMEOUT_SECONDS` | `7200` (2 h) | Hard ffmpeg timeout per job. |
| `SCREENLOOP_FFPROBE_TIMEOUT_SECONDS` | `30` | ffprobe timeout for uploads and duration checks. |

## TV polling and DLNA

The defaults favour a responsive panel. With many TVs, raise the poll intervals to cut CPU use — polling, not memory, is what caps how many screens one server can drive.

| Variable | Default | What it does |
|---|---|---|
| `SCREENLOOP_POLL_LOOP_INTERVAL` | `1` | Worker loop interval, seconds. |
| `SCREENLOOP_PING_POLL` | `2` | Fast host reachability check. |
| `SCREENLOOP_OFFLINE_POLL` | `3` | DLNA rediscovery for reachable but not ready TVs. |
| `SCREENLOOP_ONLINE_POLL` | `5` | Full DLNA/SOAP status poll for online TVs. |
| `SCREENLOOP_SSDP_TIMEOUT` | `2` | Per-target SSDP discovery timeout. |
| `SCREENLOOP_DLNA_WARMUP` | `8` | Seconds to let a TV warm up after a command. |
| `SCREENLOOP_SOAP_TIMEOUT` | `20` | Timeout for UPnP/DLNA control calls. |
| `SCREENLOOP_SOAP_NEXT_TIMEOUT` | `3` | Short timeout for the optional next-item preload. |
| `SCREENLOOP_PRELOAD_NEXT_URI` | `true` | Best-effort `SetNextAVTransportURI` for TVs that support it. |
| `SCREENLOOP_PUSH_COOLDOWN` | `5` | Minimum interval between pushes to the same TV. |
| `SCREENLOOP_AUTO_ADVANCE_END_GRACE` | `5` | Extra seconds after a known duration before pushing the next item when a TV keeps reporting `PLAYING`. |
| `SCREENLOOP_AUTO_ADVANCE_REPLAY_AFTER` | `8` | Seconds of repeated `PLAYING` on the same item before treating the TV as looping. |
| `SCREENLOOP_AUTO_ADVANCE_REPLAY_COOLDOWN` | `30` | Pause between such automatic advances. |
| `SCREENLOOP_AUTO_ADVANCE_UNKNOWN_DURATION_AFTER` | `60` | Seconds before advancing when an item's duration is unknown. |

## Nodes

Node agent variables (`SCREENLOOP_NODE_*`) are documented in [nodes.md](nodes.md).
