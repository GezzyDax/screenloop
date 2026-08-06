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
python3 -m ruff check screenloop tests scripts
python3 -m mypy screenloop
python3 -m unittest discover -s tests
docker compose build
```

To reproduce CI's end-to-end check, boot the real images and exercise the API:

```bash
docker compose build
docker tag screenloop-screenloop screenloop:smoke
docker tag screenloop-screenloop-ui screenloop-ui:smoke
./scripts/smoke.sh all
```

It runs in its own compose project against its own volume, and on ports 18099
and 18098, so it never touches a Screenloop you already have running. Override
with `SCREENLOOP_HTTP_PORT` / `SCREENLOOP_UI_PORT` if those are taken too.

### Schema changes

`tests/test_migrations.py` replays database dumps from past releases through
today's `Store.init_schema` and asserts every row survives. When you change the
schema, add the column through `Store._ensure_column` rather than editing the
`CREATE TABLE` body — the `CREATE TABLE IF NOT EXISTS` statements never run
against an existing database.

Capture a fixture for each release that changes the schema:

```bash
git worktree add /tmp/screenloop-vX.Y.Z vX.Y.Z
cd /tmp/screenloop-vX.Y.Z
PYTHONPATH=. python scripts/schema_fixture.py \
  /path/to/repo/tests/fixtures/schema/vX.Y.Z.sql
```

## Commit Messages

Use Conventional Commits so releases can be versioned automatically:

- `fix: correct playlist advancement` creates a patch release.
- `feat: add LG profile options` creates a minor release.
- `feat!: change config format` or `BREAKING CHANGE:` creates a major release.
- `docs:`, `test:`, `chore:`, and `refactor:` normally do not create a release by themselves.

Every commit type ends up in the changelog, including `chore(deps)` from
Dependabot — the changelog is meant to be a full record of what went into a
version, not a highlight reel.

## Branch Flow

`dev` is where work is integrated and tested; `main` is the released state.

```
feat/… ──PR──► dev ──PR──► main ──► auto-release ──► vX.Y.Z
```

1. Branch off `dev` as `feat/…` or `fix/…`, open a pull request into `dev`,
   merge it once CI is green.
2. Run `ghcr.io/gezzydax/screenloop:dev` on a stand and confirm the change
   behaves on real hardware.
3. Open a pull request from `dev` into `main` and **Rebase and merge** it. That
   is the release gate.

| Ref | What it is | Images |
| --- | ---------- | ------ |
| `feat/…`, `fix/…` | a single change under review | none — the pull request only builds |
| `dev` | integration branch, everything lands here first | `dev`, `sha-…` |
| `main` | released state | `main`, `sha-…` |
| `vX.Y.Z` | a release, cut automatically from `main` | `latest`, `X.Y.Z`, `X.Y` |

### Releases are automatic

Merging into `main` means releasing. Release Please opens its version pull
request and immediately enables auto-merge on it, so the tag, the GitHub
release, `latest`, and the versioned GHCR tags follow on their own once CI
passes. Nothing is re-tested there — the tree was already checked on `dev` and
again on the promotion pull request.

One release bumps the version **once**, by the strongest commit type in it: a
promotion carrying ten `feat:` commits produces a single minor bump, not ten.
Promote per finished piece of work if you want each to get its own version.

### Keeping `dev` and `main` in step

Rebase-merging a pull request rewrites its commits, so after a promotion the
same changes exist under two sets of hashes and `main` is no longer an ancestor
of `dev`. The `Sync dev` workflow fixes this automatically: once CI succeeds on
`main` it rebases `dev` onto it and force-pushes. `git rebase` drops the
already-applied commits by patch id, so only genuinely new work is replayed.

If that rebase hits a conflict, the workflow fails and leaves it to you:

```bash
git checkout dev && git fetch origin
git rebase origin/main
git push --force-with-lease origin dev
```

**Never use `git merge` to sync a branch with its base** — not locally, and not
via the pull request page's **"Update branch"** button, which performs a merge.
A merge commit inside a branch disables GitHub's "Rebase and merge" option and
breaks `main`'s linear-history requirement; CI's `no-merge-commits` job rejects
any pull request whose branch contains one.

### Merge style

- **Rebase and merge** for multi-commit branches, and always for the `dev` →
  `main` promotion — it keeps every Conventional Commit visible, which gives
  Release Please the most detailed changelog.
- **Squash and merge** is fine for small, single-purpose branches into `dev` —
  the squash message includes every underlying commit body (`COMMIT_MESSAGES`
  setting), so `feat!:`/`BREAKING CHANGE:` is still detected.
- Either way the pull request title must follow Conventional Commits — a bot
  lints it, and it becomes the commit header when squashed.

## Pull Requests

Keep PRs focused and include:

- What changed and why.
- Manual TV/device testing if playback behavior changed.
- Screenshots for web UI changes.
- Notes for security-sensitive changes.

Do not commit local media, SQLite databases, transcode output, `.env`, private IP inventories, or generated caches.
