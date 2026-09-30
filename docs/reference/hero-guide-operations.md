# Hero guide refresh operations

The current hero-guide refresh is an operator command, separate from online
`hero.guide` queries. Queries read Redis only. The refresh command makes live
D2PT requests and publishes successful source partitions to the shared Redis
cache. Offline tests do not execute this command. A historical local WSL
deployment record includes a full refresh and an enabled guide timer; it does not
prove the timer fired or describe another host's installation.

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

## Optional systemd schedule

The repository provides `deploy/systemd/dotamind-hero-guides.service` and
`deploy/systemd/dotamind-hero-guides.timer` as production deployment templates.
They use `/opt/dotamind`, `compose.prod.yml`, and daily 03:00 Asia/Shanghai
scheduling with no random delay. The repository timer has `Persistent=false`.

The local Ubuntu WSL installation is separate: its installed unit uses
`/home/lip233/code/dotamind`, `compose.wsl.yml`, and a timer with
`Persistent=true`. The local deployment record says this timer was enabled.
These WSL paths and catch-up behavior do not describe the production template or
other hosts. Check the actual host's unit and timer state before operating it.

An operator who is authorized to configure this host can install the templates
and enable the timer:

```bash
sudo install -m 0644 deploy/systemd/dotamind-hero-guides.service \
  /etc/systemd/system/dotamind-hero-guides.service
sudo install -m 0644 deploy/systemd/dotamind-hero-guides.timer \
  /etc/systemd/system/dotamind-hero-guides.timer
sudo systemctl daemon-reload
sudo systemctl enable --now dotamind-hero-guides.timer
```

The install commands above are not run by application deployment or the
repository's offline tests. The local WSL timer's enabled state is historical
host evidence, not proof of a successful scheduled invocation. The service's
`SuccessExitStatus=3` treats a same-container
overlap skip as successful; exit code `4` remains visible as a partial refresh
requiring review.

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

Offline tests use fake clients and Redis. They do not verify a successful
scheduled invocation, the live deployment's Redis AOF/volume recovery, or
real-model answer quality. A historical local refresh processed 127 heroes with
763 requests and published 635 Pub and 127 Pro partitions, including valid
empty responses; Sven and Anti-Mage Service queries succeeded. This evidence is
specific to that local Redis-backed run. It does not establish file migration,
API hot reload, or the state of another deployment. The process lock is
intentionally container-local; a deployment with multiple API containers needs
an explicit coordination decision before scheduling this command on more than
one container.

## Persistent data initialization and guide import (commands implemented; not run)

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

No real data root has been initialized and no Redis migration has been run. The
API still reads its bundled catalog, guide queries and the refresh CLI/timer
still use Redis, and no unified scheduled updater or API hot reload is enabled.
Keep the Redis guide data until migration verification and API switching have
been separately accepted.
