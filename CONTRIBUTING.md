# Contributing

## Development Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export SCREENLOOP_SECRET_KEY="$(openssl rand -hex 32)"
export SCREENLOOP_BOOTSTRAP_PASSWORD="dev-$(openssl rand -hex 4)"
echo "bootstrap admin password: $SCREENLOOP_BOOTSTRAP_PASSWORD"
python -m screenloop
```

## Checks

Run before opening a pull request:

```bash
python3 -m ruff check screenloop tests
python3 -m mypy screenloop
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

**Never use `git merge` to sync a branch with its base.** Always `git rebase` (e.g. `git fetch origin && git rebase origin/main` on `dev`, or `git rebase origin/dev` on a feature branch). A merge commit inside a branch disables GitHub's "Rebase and merge" option on the PR and breaks `main`'s linear-history requirement — CI's `no-merge-commits` job rejects any PR whose branch contains one, so resolve conflicts via rebase and force-push instead.

When merging a PR into `main`:
- Prefer **Rebase and merge** for the periodic `dev → main` PR — it keeps every individual Conventional Commit visible in `main`'s history, which gives Release Please the most detailed changelog.
- **Squash and merge** is fine for small, single-purpose branches — the squash commit message includes every underlying commit body (`COMMIT_MESSAGES` setting), so Release Please still detects `feat!:`/`BREAKING CHANGE:` correctly either way.
- Whichever you pick, make sure the PR title itself follows Conventional Commits — a bot lints it on every PR, and it becomes the commit header when squashed.

## Pull Requests

Keep PRs focused and include:

- What changed and why.
- Manual TV/device testing if playback behavior changed.
- Screenshots for web UI changes.
- Notes for security-sensitive changes.

Do not commit local media, SQLite databases, transcode output, `.env`, private IP inventories, or generated caches.
