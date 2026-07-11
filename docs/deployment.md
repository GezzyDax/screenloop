# Deployment Guide

## Architecture and ports

Screenloop runs as two containers on the **host network** (required for SSDP discovery and direct TV streaming):

```
LAN clients (browsers) ──► screenloop-ui  (nginx, port 8098)
                              │ proxies /api and /stream
                              ▼
                           screenloop     (FastAPI, port 8099)
                              ▲
TVs (DLNA renderers) ─────────┘  direct HTTP range requests to :8099/stream
                              plus outgoing SSDP/SOAP from the backend to TVs
```

- `8098` (`SCREENLOOP_UI_PORT`) — the web panel. This is the only port users need.
- `8099` (`SCREENLOOP_HTTP_PORT`) — backend API and media streaming. TVs fetch signed `/stream` URLs from it directly.

**Important:** because of host networking, port 8099 is reachable from the whole LAN, not only through nginx. The API is protected by sessions/CSRF and stream URLs are signed and bound to TV addresses, but you should still firewall it down to the TV subnet plus localhost — see [hardening.md](hardening.md).

## Data

Everything lives in the `screenloop-data` Docker volume:

- `/data/db/screenloop.sqlite3` — SQLite state (users, TVs, playlists, events).
- `/data/media` — uploaded originals.
- `/data/transcoded` — TV-safe MP4 copies (rebuildable from originals).

Backup and restore: [backup.md](backup.md).

## Reverse proxy with TLS

For access beyond the trusted LAN, terminate TLS in front of the UI port and enable secure cookies:

```bash
# .env
SCREENLOOP_COOKIE_SECURE=true
SCREENLOOP_TRUSTED_PROXY_CIDRS=127.0.0.1/32,::1/128   # where your proxy connects from
```

### Caddy

```caddy
screenloop.example.com {
    reverse_proxy 127.0.0.1:8098
}
```

### nginx

```nginx
server {
    listen 443 ssl;
    server_name screenloop.example.com;
    ssl_certificate     /etc/letsencrypt/live/screenloop.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/screenloop.example.com/privkey.pem;

    client_max_body_size 2g;

    location / {
        proxy_pass http://127.0.0.1:8098;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # SSE live updates
    location /api/v1/stream/events {
        proxy_pass http://127.0.0.1:8098;
        proxy_set_header Host $host;
        proxy_buffering off;
        proxy_read_timeout 1h;
    }
}
```

Notes:

- TVs must still reach `http://<server-ip>:8099` directly — do not force TV traffic through the TLS proxy.
- If the panel is reached through a different public URL, set `SCREENLOOP_PUBLIC_URL` only if TVs should use it for stream URLs (usually they should not).
- `SCREENLOOP_TRUSTED_PROXY_CIDRS` controls who may supply `X-Forwarded-For`; keep it limited to the proxy host.

## Updating and rolling back

```bash
cd /opt/screenloop
./update.sh              # roll forward on the current channel
./update.sh --rollback 1.5.0   # pin both images to a released version and restart
```

Rollback only switches image tags; the data volume is untouched. Database schema migrations are additive, so rolling the app back after a newer version created columns is safe for reads/writes of known columns, but prefer restoring a matching DB backup when downgrading across many versions.
