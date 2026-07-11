# Backup and Restore

All state lives in the `screenloop-data` Docker volume. A full backup is one tar archive of that volume.

## Backup

```bash
cd /opt/screenloop
docker compose stop screenloop          # stop writes for a consistent SQLite copy
docker run --rm \
  -v screenloop_screenloop-data:/data:ro \
  -v "$(pwd)":/backup \
  alpine tar czf /backup/screenloop-backup-$(date +%F).tar.gz -C /data .
docker compose start screenloop
```

The volume name may differ if your compose project name is not `screenloop` — check with `docker volume ls | grep screenloop-data`.

To save space you can exclude `transcoded/` — it is fully rebuildable from originals (each media just re-transcodes after restore):

```bash
... alpine tar czf /backup/screenloop-backup-$(date +%F).tar.gz -C /data --exclude=./transcoded .
```

Also back up `/opt/screenloop/.env` (contains your `SCREENLOOP_SECRET_KEY`; keep the copy as private as the original).

## Restore

On a clean host, install Screenloop first (installer or compose), then:

```bash
cd /opt/screenloop
docker compose down
docker run --rm \
  -v screenloop_screenloop-data:/data \
  -v "$(pwd)":/backup \
  alpine sh -c "rm -rf /data/* && tar xzf /backup/screenloop-backup-YYYY-MM-DD.tar.gz -C /data"
docker compose up -d
```

Restore the saved `.env` before `up -d`. If you restore data without the original `SCREENLOOP_SECRET_KEY`, users and passwords keep working (they are stored as hashes), but all sessions and any signed stream URLs become invalid — TVs simply get re-pushed.

## What a full disaster recovery needs

1. The volume archive (database + media).
2. The `.env` file (secret key, ports, image pins).
3. Nothing else — TVs, playlists, users and events are all in the database.
