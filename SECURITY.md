# Security Policy

## Supported Use

Screenloop is built for trusted local networks. Do not expose the app directly to the public Internet.

If remote access is required, run it behind a reverse proxy with TLS, strong authentication, and IP/network restrictions.

## Baseline Protections

- Startup rejects empty/default passwords unless `SCREENLOOP_ALLOW_INSECURE_AUTH=true` is explicitly set.
- `SCREENLOOP_SECRET_KEY` is required for CSRF tokens and signed stream URLs.
- Mutating web forms require CSRF tokens.
- Media stream URLs require signed tokens.
- Basic security headers are added to web responses.
- Upload size is limited by `SCREENLOOP_MAX_UPLOAD_BYTES`.

## Reporting Vulnerabilities

Please open a private security advisory on GitHub if available, or contact the maintainer privately before publishing details. Include reproduction steps, affected version or commit, and impact.
