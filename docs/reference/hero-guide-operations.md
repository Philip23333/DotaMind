# Hero guide operations

## Supported data flow

Daily `refresh-all` writes guide partitions to the shared file data root through
`FileHeroGuideCache`. The API mounts that same volume read-only and reads the
requested files directly for each `hero.guide` query. It does not cache file
contents in Redis, and it does not fall back to Redis when a file is missing or
invalid. If `DOTAMIND_DATA_DIR` is not configured, the guide tool is not
registered.

The old Redis guide-refresh CLI and its systemd service/timer templates have been
removed. Redis remains configured for other application stores. The only guide
operation that reads Redis is the explicit, one-time `migrate-guides` importer
for deployments that need to preserve old guide snapshots.

## Manual refresh

Run the supported file-backed refresh from the Compose project directory. Use
the same Compose project name and volume configuration as the running API:

```bash
docker compose -f compose.prod.yml -f compose.data.yml \
  run --rm --no-deps -T data-updater refresh-guides
```

For WSL, run `./scripts/compose-wsl.sh run --rm --no-deps -T data-updater
refresh-guides`. The helper loads `compose.wsl.yml` and `compose.data.yml`; the
updater mounts the shared volume read-write. `refresh-guides` does not require a
Catalog snapshot or Redis URL. The unified `refresh-all` command is the daily path
and also updates Catalog, patch records, and images.

The refresher gets the hero list once, requests Pub positions 1 through 5 and Pro
once per hero in source order, and waits one second between requests. Successful
partitions are atomically replaced as files. Fetch or parse failure preserves
that partition's previous successful snapshot. A valid empty response is
published as an empty snapshot.

The command takes the shared data-root update lock, which prevents overlapping
updates from processes and containers mounting the same data root. Cancellation
waits for an in-flight urllib worker before releasing the lock; urllib timeouts
are not a strict total-run deadline.

## API file reads

The API must use both the base Compose file and the data overlay:

```bash
docker compose -f compose.prod.yml -f compose.data.yml \
  up -d --no-deps --force-recreate api
```

For WSL, use `./scripts/compose-wsl.sh up -d --no-deps --force-recreate api`;
the helper loads the base file and overlay. The overlay sets `DOTAMIND_DATA_DIR`
and mounts the shared data volume read-only. The data root must already contain a valid
Catalog snapshot because API startup validates that snapshot. Guide query reads
go directly to `guides/pub/<hero_id>/<position>.json` and
`guides/pro/<hero_id>.json`. Atomic file replacement makes new partitions
visible to the next query without restarting the API.

Without the overlay, the API has no `DOTAMIND_DATA_DIR` and does not register
`hero.guide`. It does not read guide data from Redis. Keep Redis configured for
the other application services that use it.

## One-time legacy Redis import

Use this only when an existing deployment's Redis guide snapshots must be
preserved. First initialize the file data root's Catalog if needed:

```bash
docker compose -f compose.prod.yml -f compose.data.yml \
  run --rm --no-deps -T data-updater init-catalog
```

Then run the importer:

```bash
docker compose -f compose.prod.yml -f compose.data.yml \
  run --rm --no-deps -T data-updater migrate-guides
```

The importer reads only known Pub and Pro keys for Catalog heroes. It does not
call D2PT, scan arbitrary Redis keys, update the source Redis entries, or refresh
missing partitions. Identical file partitions are verified and skipped;
conflicting or corrupt targets stop the import. Review its report and read back
representative partitions before switching the API. WSL was populated by the
file refresher directly and did not import the previous Docker Desktop Redis
volume. Production migration remains a separate operator decision.

## Scheduling and deployment checks

`deploy/systemd/dotamind-data-update.service` and `.timer` are the supported
schedule templates. They run `refresh-all` through the one-shot updater service
at 03:00 Asia/Shanghai with `Persistent=false`. The repository templates do not
prove that a host has installed or enabled the timer; check systemd and its
journal on that host.

If a host still has an older installed `dotamind-hero-guides.timer`, disable it
before enabling the unified data-update timer. Its source template is no longer
in this repository, but deleting a repository file does not remove an already
installed systemd unit. Do not run both refresh schedules.

After a deployment, verify that the API container has `DOTAMIND_DATA_DIR`, the
shared-data mount is read-only, the updater uses the same volume read-write, API
health is good, and a representative `hero.guide` query reads the file-backed
partitions. Do not print full container environments or expanded Compose
configuration while checking settings.
