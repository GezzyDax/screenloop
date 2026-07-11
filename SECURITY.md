# Security Policy

## Supported Versions

| Version | Supported |
| ------- | --------- |
| latest stable release (1.x) | yes |
| `dev` builds | best effort, no guarantees |
| < 1.0 | no |

Security fixes land in `dev` and are released to stable as patch versions.

## Supported Use

Screenloop is built for trusted local networks. Do not expose the app directly to the public Internet.

If remote access is required, run it behind a reverse proxy with TLS, strong authentication, and IP/network restrictions. See [docs/deployment.md](docs/deployment.md) and the [hardening checklist](docs/hardening.md).

## Baseline Protections

- Startup rejects empty, placeholder, or publicly documented secrets unless `SCREENLOOP_ALLOW_INSECURE_AUTH=true` is explicitly set.
- `SCREENLOOP_SECRET_KEY` is required for CSRF tokens and signed stream URLs.
- Cookie sessions renew on activity up to an absolute lifetime cap; users can list and revoke their own sessions.
- Mutating API calls require CSRF tokens; roles are `viewer` < `operator` < `admin`, and the last active admin cannot be demoted or disabled.
- Media stream URLs are signed and bound to the requesting TV address, with a configurable lifetime.
- Login attempts are rate-limited per IP and per username; uploads are size-limited while streaming to disk.
- Security audit events are retained separately from the service event stream and hidden from the viewer role.

## Reporting Vulnerabilities

Please open a private security advisory on GitHub if available, or contact the maintainer privately before publishing details. Include reproduction steps, affected version or commit, and impact.

You can expect an initial response within 7 days. Please allow up to 90 days for a coordinated fix and release before public disclosure.
