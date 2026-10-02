# Hero guide refresh operations

The hero-guide refresh commands are separate from online `hero.guide` queries.
When `DOTAMIND_DATA_DIR` is configured, queries read file partitions from that
root; otherwise they read Redis when configured. File mode does not fall back to
Redis, and the tool is not registered if neither store is configured. The legacy
Redis refresh command makes live D2PT requests and publishes successful source partitions to the shared Redis
cache. Offline tests do not execute this command. The fresh-data WSL cutover now
uses file-backed guides and the unified timer; the legacy Redis timer is disabled
there. This does not prove a scheduled firing or describe another host's state.

## Preconditions and boundaries

- Run the command from a Linux host with Docker Compose available and the
  DotaMind API container already running.
- The API container must have a valid `DOTAMIND_REDIS_URL` and network access to
  D2PT. The CLI reads the URL from its process environment; it does not load a
  `.env` file itself. `docker compose exec` runs it with the container's
  configured environment.
- Use one API container for scheduled refreshes. The non-blocking `flock` at
  `/tmp/dotamind-hero-guide-refresh.lock` coordinates only CLI processes sharing
  that container's `/tmp`; it is not a distributed lock and does not prevent
  overlap across API replicas or hosts.
- The lock file remains after the command exits. File presence does not indicate
  that a lock is held; do not remove it to “clear” a refresh. Kernel lock state
  follows the open file descriptor and is released when the CLI closes it.
- Successful Pub/Pro partitions replace their complete cache snapshots. A
  failed fetch or parse records that partition's attempt failure and keeps its
  last successful snapshot. Publication is per partition, not an atomic
  all-heroes switch. A valid empty response is published as an empty snapshot.
- The CLI is not an HTTP endpoint or model-facing tool. Startup and cache reads
  do not trigger refreshes.

## Manual refresh

From the deployment Compose project directory, run the same command used by the
systemd service:

```bash
docker compose -f compose.prod.yml exec -T api \
  python -m app.vnext.hero_guides refresh
```

The command acquires the container-local lock before creating the Redis and D2PT
clients, pings Redis, performs one serial refresh, closes Redis, and then releases
the lock. It writes one JSON result line to stdout and avoids exception text or
credentials.

Exit codes are:

| Code | Meaning |
|---:|---|
| `0` | All attempted partitions succeeded, including valid empty responses. |
| `1` | Redis, cache, lock, or refresh failure. Inspect the safe `reason` field. |
| `2` | Invalid CLI usage or missing `DOTAMIND_REDIS_URL`. |
| `3` | Another refresh already holds the container-local lock; no work was started. |
| `4` | Refresh completed with one or more partition failures; successful partitions may have published. |
| `130` | Cancelled by SIGINT or SIGTERM. |

On cancellation, the coroutine is cancelled, but Python cannot forcibly stop an
urllib request already running in a worker thread. The CLI waits for that worker
to finish before closing Redis and releasing the lock. The urllib timeout is
not a strict total-request or whole-run deadline. Do not assume killing only the host-side
`docker compose exec` command proves the in-container refresh process has ended.

## File-backed refresh command (implemented; run on WSL; production pending)

The separate file-backed entrypoint reuses `HeroGuideRefresher` and writes
partitions through `FileHeroGuideCache`:

```bash
cd apps/api
python -m app.vnext.data_updates refresh-guides --data-dir /absolute/data/root
```

`--data-dir` takes precedence over `DOTAMIND_DATA_DIR`; either must be an
absolute path. The command does not require `DOTAMIND_REDIS_URL`, a catalog
snapshot, or a Redis connection. It uses the D2PT hero list, keeps the serial
Pub-position-then-Pro request order and one-second waits, and writes complete
source snapshots to the guide files.

It acquires `<data_root>/.update.lock` first and then
`/tmp/dotamind-hero-guide-refresh.lock`, releasing them in reverse order. The
second lock prevents overlap with the legacy Redis refresh command only for
processes sharing that lock path inside one API container; it is not distributed.
On cancellation, the command waits for an in-flight HTTP or file worker before
releasing either lock. Its one-line JSON includes `"operation":"refresh-guides"`
and the refresh report. Exit codes are 0 for success, 4 for partial completion,
1 for execution failure, 2 for invalid configuration, 3 when either lock is
busy, and 130 for cancellation.

The WSL API reads the shared file volume through its read-only mount. The old
Redis guide timer is disabled there, and the unified data-update timer is enabled.
The file-backed command has offline fake-client tests and completed a real D2PT
refresh on WSL. Do not install the Redis and file refresh commands together as
daily jobs.

## systemd schedule templates

The repository retains `deploy/systemd/dotamind-hero-guides.service` and
`deploy/systemd/dotamind-hero-guides.timer` as legacy production templates. They
run the Redis refresh command. The new `dotamind-data-update.service` and
`dotamind-data-update.timer` templates run unified file updates through the
one-shot updater container. They use `/opt/dotamind`, both production Compose
files, daily 03:00 Asia/Shanghai scheduling, and `Persistent=false`. The new timer
is not installed or enabled by this repository change. Do not run both schedules
as daily jobs after the file-backed cutover.

The local Ubuntu WSL installation is separate: the legacy Redis guide timer is
disabled. The unified data-update service is installed with a local drop-in using
`/home/lip233/code/dotamind`, `/usr/bin/docker`, and the WSL Compose files. Its
timer uses the repository template's `Persistent=false` and is enabled for
03:00 Asia/Shanghai. These WSL paths do not describe the production template or
other hosts. No scheduled firing has yet been observed.

The following commands install the legacy Redis guide timer only:

```bash
sudo install -m 0644 deploy/systemd/dotamind-hero-guides.service \
  /etc/systemd/system/dotamind-hero-guides.service
sudo install -m 0644 deploy/systemd/dotamind-hero-guides.timer \
  /etc/systemd/system/dotamind-hero-guides.timer
sudo systemctl daemon-reload
sudo systemctl enable --now dotamind-hero-guides.timer
```

The install commands above are not run by application deployment or the
repository's offline tests. The legacy Redis guide timer is disabled on WSL; the
unified timer is enabled there, but has not fired yet. The legacy service's
`SuccessExitStatus=3` treats a same-container overlap skip as
successful; exit code `4` remains visible as a partial refresh requiring review.
The new data-update service also treats only lock-busy exit code `3` as
successful. For persistent data initialization, Redis import, API cutover, and
rollback order, see [`data-update-operations.md`](data-update-operations.md).

Read-only checks for timer and recent service state:

```bash
systemctl list-timers --all dotamind-hero-guides.timer
systemctl status dotamind-hero-guides.timer --no-pager
journalctl -u dotamind-hero-guides.service --since today --no-pager
```

The service log contains the CLI's safe status/report JSON. Do not add commands
that dump the full container environment, Compose-expanded configuration, or
credentials while diagnosing refresh failures.

## Acceptance still required

Offline tests use fake clients and Redis. The 2026-10-02 WSL file refresh
processed 127 heroes with 763 requests and published 635 Pub and 127 Pro
partitions, including 143 empty Pub and 3 empty Pro partitions. Sven and
Anti-Mage position-1 Service queries each read one Pub guide and five Pro
examples. The API-only container recreation preserved those reads through the
read-only shared volume. The unified timer is enabled but has not had its first
scheduled firing. Production state and real-model answer quality remain separate
checks. The process lock is intentionally container-local; a deployment with
multiple API containers needs an explicit coordination decision before scheduling
the legacy Redis refresh command on more than one container.

## Persistent data initialization and guide import (WSL initialized; Redis import pending)

The operator CLI provides two offline-verifiable commands. They are separate
from the existing guide refresh command above and do not change API reads or the
timer.

From `apps/api`, initialize the five-file catalog first:

```bash
python -m app.vnext.data_updates init-catalog --data-dir /absolute/data/root
```

The source defaults to the catalog bundled with the API. To copy another local
validated catalog, pass `--source-dir /absolute/source/directory`. The command
copies only `manifest.json`, `dota2_heroes.json`, `dota2_abilities.json`,
`dota2_items.json`, and `sync_audit.json`; images and patch records are not
included. It publishes only if `catalog/current.json` has no valid snapshot. A
valid existing snapshot is reported as `already_initialized` without reading
the source; a damaged pointer or snapshot fails and is never overwritten.

Then import guide partitions:

```bash
python -m app.vnext.data_updates migrate-guides --data-dir /absolute/data/root
```

An explicit `--data-dir` takes precedence over `DOTAMIND_DATA_DIR`. If the
argument is omitted, that environment variable must contain an absolute path;
there is no repository or working-directory default. The migration command
requires `DOTAMIND_REDIS_URL` from the process environment and does not accept a
Redis URL argument. It takes hero IDs from the current published catalog, reads
only the known Pub and Pro Redis partitions, and invokes the existing importer.
It does not request D2PT data, scan arbitrary Redis keys, publish refresh data,
or delete Redis entries.

Both commands acquire a non-blocking exclusive lock at
`<data_root>/.update.lock`. Guide migration next acquires the existing
`/tmp/dotamind-hero-guide-refresh.lock`; it releases the locks in reverse order.
The refresh lock coordinates only processes sharing that path. Therefore guide
migration must run in the same API container as the existing refresh CLI; this
lock does not coordinate other containers or hosts. If either lock is busy, the
command prints `{"status":"skipped","reason":"already_running"}` and exits
with code 3 without starting storage or Redis work.

Successful commands print one JSON line. Repeating `init-catalog` safely skips
an already published valid snapshot. Repeating migration verifies and skips
identical file partitions; conflicting or corrupt targets fail while preserving
both file data and Redis data. Exit code 1 means an execution/storage/Redis
failure, 2 means invalid arguments or missing configuration, and 130 means
interruption. Error JSON uses fixed reasons and excludes credentials and
exception text.

The WSL data root was initialized from the bundled Catalog and the API uses it in
file mode. No Redis guide migration was run: this deployment used a fresh volume,
and the previous Docker Desktop data remains untouched. A real file-backed guide
refresh has been performed on WSL. The old Redis guide timer is disabled and the
unified data-update timer is enabled, although no scheduled firing has yet been
observed. The production Redis migration, API switch, and timer installation are
still pending. Keep production Redis guide data until any production migration is
verified and accepted.

## Production API file-read cutover order

For a future cutover, use this order and verify each step before proceeding:

1. Prepare the persistent data root and publish a valid Catalog snapshot.
2. Import the intended Redis guide partitions with `migrate-guides`, then verify
   the migration report and representative file entries.
3. Pause the existing Redis guide timer and confirm no refresh is still running.
4. Confirm the final imported files are valid. Investigate any conflicts; do not
   force overwrite them.
5. Configure the API with `DOTAMIND_DATA_DIR` using the opt-in Compose overlay.
   After validating a manual `refresh-all`, replace the old Redis guide schedule
   with the unified data-update timer. See
   [`data-update-operations.md`](data-update-operations.md) for the full sequence.
6. Verify API queries, file refresh, and persistence across API-container
   recreation. Only after that acceptance should operators consider removing old
   Redis guide data.

This sequence remains the production procedure. The local WSL cutover is complete
as recorded above; it does not establish that a production host has switched to
the shared data volume or enabled its timer.
