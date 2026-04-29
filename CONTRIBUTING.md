# Contributing

## Development Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
SCREENLOOP_PASSWORD=dev-password SCREENLOOP_SECRET_KEY=dev-secret-change-me python -m screenloop
```

## Checks

Run before opening a pull request:

```bash
python3 -m py_compile dlna_push.py screenloop/*.py tests/test_core.py
python3 -m unittest discover -s tests
docker compose build
```

## Pull Requests

Keep PRs focused and include:

- What changed and why.
- Manual TV/device testing if playback behavior changed.
- Screenshots for web UI changes.
- Notes for security-sensitive changes.

Do not commit local media, SQLite databases, transcode output, `.env`, private IP inventories, or generated caches.
