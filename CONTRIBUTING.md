# Contributing

## Development Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
SCREENLOOP_BOOTSTRAP_PASSWORD=dev-password-please-change SCREENLOOP_SECRET_KEY=dev-secret-change-me python -m screenloop
```

## Checks

Run before opening a pull request:

```bash
python3 -m py_compile dlna_push.py screenloop/*.py tests/test_core.py
python3 -m unittest discover -s tests
docker compose build
```

## Commit Messages

Use Conventional Commits so releases can be versioned automatically:

- `fix: correct playlist advancement` creates a patch release.
- `feat: add LG profile options` creates a minor release.
- `feat!: change config format` or `BREAKING CHANGE:` creates a major release.
- `docs:`, `test:`, `chore:`, and `refactor:` normally do not create a release by themselves.

Release Please opens a release PR from commits merged into `main`. Merging that PR creates the GitHub release and tag; the Docker workflow then publishes the GHCR image for that tag.

## Branch Flow

Use `dev` for integration and testing. Push feature/fix branches into pull requests targeting `dev`, verify CI and the `ghcr.io/gezzydax/screenloop:dev` image, then open a pull request from `dev` to `main`.

Do not commit directly to `main`. `main` is the stable branch, drives `latest` images, and is protected after repository setup.

## Pull Requests

Keep PRs focused and include:

- What changed and why.
- Manual TV/device testing if playback behavior changed.
- Screenshots for web UI changes.
- Notes for security-sensitive changes.

Do not commit local media, SQLite databases, transcode output, `.env`, private IP inventories, or generated caches.
