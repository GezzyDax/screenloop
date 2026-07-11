# Production Hardening Checklist

Screenloop is designed for trusted LANs. Before exposing it to a larger network, walk this list.

## Secrets

- [ ] `SCREENLOOP_SECRET_KEY` is a generated value (`openssl rand -hex 32`), not a placeholder. The app refuses known placeholders at startup.
- [ ] `SCREENLOOP_BOOTSTRAP_PASSWORD` was strong, and **removed from `.env` after the first login** — it is only needed to create the first admin.
- [ ] `.env` is `chmod 600` (the installer and updater enforce this; re-check after manual edits).

## Network

- [ ] Host networking exposes the backend port (`8099`) to the whole LAN. Firewall it so only TVs and localhost can reach it, e.g. with ufw:

  ```bash
  ufw allow from 192.168.10.0/24 to any port 8099 proto tcp   # TV subnet
  ufw deny 8099/tcp
  ufw allow 8098/tcp                                          # web panel
  ```

- [ ] `SCREENLOOP_ALLOWED_TV_CIDRS` is set to your TV subnets — this also restricts which control URLs and TV addresses can be configured.
- [ ] Remote access goes through a TLS reverse proxy ([deployment.md](deployment.md)) with `SCREENLOOP_COOKIE_SECURE=true`.
- [ ] `SCREENLOOP_TRUSTED_PROXY_CIDRS` lists only your proxy.

## Application

- [ ] `SCREENLOOP_API_DOCS=false` in production — disables `/docs`, `/redoc`, `/openapi.json`.
- [ ] Per-user accounts with the smallest sufficient role (`viewer` < `operator` < `admin`); the last active admin cannot be demoted.
- [ ] Users periodically review **Profile → My sessions** and revoke unknown sessions.
- [ ] `SCREENLOOP_SESSION_TTL_SECONDS` / `SCREENLOOP_SESSION_MAX_LIFETIME_SECONDS` tightened if your environment requires it.

## Secret key rotation

Changing `SCREENLOOP_SECRET_KEY`:

- invalidates all CSRF tokens and signed stream URLs immediately (TVs get re-pushed automatically);
- does **not** invalidate sessions (they are stored server-side) and does not affect passwords.

Rotate by editing `.env` and `docker compose up -d`.

## Updates

- [ ] Subscribe to releases on GitHub; `SCREENLOOP_UPDATE_CHECK=true` shows update hints in the panel.
- [ ] Prefer pinned semver image tags over `latest` on production installs; use `./update.sh --rollback <version>` for quick rollback.
