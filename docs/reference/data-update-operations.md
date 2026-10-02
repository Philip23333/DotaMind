# Persistent data update operations

This document describes the file-backed data path and its operational procedure.
The fresh-data WSL cutover was executed on 2026-10-02 and is recorded below.
Production remains on its existing deployment until separately cut over.

## Verified WSL deployment (2026-10-02)

- Ubuntu 26.04.1 runs Docker Engine 29.8.2 under `docker.service`; the default
  context is the local `/var/run/docker.sock`. Compose is 5.5.1 and Buildx is
  available. The daemon and the API/updater use the tested WSL host proxy
  `172.29.112.1:10808`.
- Compose project `dotamind` uses a fresh `shared-data` volume. The old Docker
  Desktop DotaMind containers were stopped; the old Desktop volumes were left
  untouched and no guide data was migrated from them.
- `init-catalog` published patch `7.41f`, revision
  `d0446e97add94e0fb29a30fdf4cc0905`. The real `refresh-all` run then skipped
  Catalog entity fetching because Valve still reported `7.41f`; it updated the
  patch record with 100 changes. The guide module succeeded for 127 heroes: 635
  Pub partitions published, 143 valid-empty Pub partitions, 127 Pro partitions
  published, and 3 valid-empty Pro partitions.
- Image refresh downloaded 1,338 of 1,488 targets and reported 150
  `download_failed` ability images. Images are optional, and this partial result
  did not block guide or text reads. A Sven image hash URL returned PNG bytes
  with matching SHA-256 and immutable cache headers.
- API health passed before and after recreating only the API container. Its
  `shared-data` mount is read-only. The other Compose containers were not
  recreated. Through the application Service, Sven and Anti-Mage position-1
  queries each read one Pub guide and five Pro examples after the API recreation.
- `dotamind-data-update.timer` is enabled and active for 03:00 Asia/Shanghai;
  its next scheduled time is 2026-10-03 03:00 CST. No scheduled firing has yet
  been observed. The old Redis guide timer is disabled and inactive. WSL must be
  running for its systemd timer to fire; no Windows wake task was added.

This is local WSL evidence only. No production deployment or Redis guide
migration was performed.

## Configuration boundary

`compose.wsl.yml` and `compose.prod.yml` each declare the API image and a
`data-updater` service using that same image. The updater is in the `maintenance`
profile, writes `shared-data` at `/var/lib/dotamind/data`, and defaults to
`--help`. It has no API dependency, port, Uvicorn command, or database migration
step. `docker compose run --rm` removes the one-shot container; it does not remove
the named volume.

`compose.data.yml` is an explicit API-only overlay. It sets
`DOTAMIND_DATA_DIR=/var/lib/dotamind/data` and mounts the volume read-only. The
original Compose files do not load this overlay, so ordinary deployments retain
their current API data mode. API and updater must use the same Compose project
name. Do not supply a different `-p`/`COMPOSE_PROJECT_NAME` when running the
updater.

The new unified updater acquires `<data_root>/.update.lock`, shared by all
containers mounting the same project volume. The old Redis-only guide command
uses `/tmp/dotamind-hero-guide-refresh.lock`; `/tmp` is normally private to each
container. That lock **cannot** prevent an old API-container Redis refresh from
overlapping a new updater in another container. Stop the old guide timer and wait
until its in-flight service is inactive before importing or switching reads.

Missing images are non-blocking: API text, Catalog, and guide reads can work
without an image manifest or downloaded image files.

## Select the Compose project

For WSL, run from the repository root. The file declares project name `dotamind`:

```bash
cd /home/lip233/code/dotamind
docker compose -f compose.wsl.yml
```

For production, run from `/opt/dotamind` and use the same project name as the
currently running API. The repository service template uses this directory and
the production Compose files:

```bash
cd /opt/dotamind
docker compose -f compose.prod.yml
```

If the running project uses an explicit project-name override, preserve that
same override for every command and the systemd service environment. Record it
before continuing.

## Migration and cutover order

Follow these steps for WSL or production, substituting `compose.wsl.yml` for
`compose.prod.yml` as appropriate. Add `-f compose.data.yml` only for the API
switch and updater runs shown below.

1. Record the current API image, Compose project name, and old guide timer state.
   Check the actual host because repository templates do not establish installed
   timer state.

2. Disable the old Redis guide timer, then confirm any already-running guide
   refresh has finished before continuing. Do not proceed while
   `dotamind-hero-guides.service` is active:

   ```bash
   sudo systemctl disable --now dotamind-hero-guides.timer
   systemctl is-active dotamind-hero-guides.service
   ```

   The old timer must remain disabled after cutover. Do not schedule it alongside
   `refresh-all`.

3. Build the updated API image without recreating or switching the running API:

   ```bash
   docker compose -f compose.prod.yml build api
   ```

   For WSL use `compose.wsl.yml`. The API image tag is shared by the updater, so
   the one-shot commands below run the same application build.

4. Initialize the named volume's Catalog before enabling API file mode:

   ```bash
   docker compose -f compose.prod.yml run --rm --no-deps -T data-updater init-catalog
   ```

   Substitute the WSL Compose file when operating locally. This first `run`
   creates the Compose-scoped named volume if needed.

5. Import and verify guide files from the existing Redis data only when
   preserving that data is part of the cutover. Redis must already be reachable
   in this Compose project; the updater service itself does not start
   dependencies:

   ```bash
   docker compose -f compose.prod.yml run --rm --no-deps -T data-updater migrate-guides
   ```

   Review the complete safe JSON report. Preserve the Redis source data. If the
   importer reports a conflict or invalid entry, investigate it; do not force
   overwrite. For the current WSL fresh deployment, skip `migrate-guides`: the
   file guide store starts empty, and the old Docker Desktop Redis volume remains
   untouched.

6. Confirm the current Catalog remains valid. For a Redis migration, also verify
   the imported guide partitions passed the importer's read-back verification.
   For the WSL fresh deployment, confirm the file guide store is empty before
   starting the API; this is expected. Repeating `init-catalog` should report an
   already initialized valid snapshot. Resolve any Catalog error before
   switching the API.

7. Opt the API into the shared volume and recreate only the API service:

   ```bash
   docker compose -f compose.prod.yml -f compose.data.yml \
     up -d --no-deps --force-recreate api
   ```

   Use `compose.wsl.yml` instead for WSL. This API mount is read-only. The updater
   remains writable. The ordinary base Compose command still does not select file
   mode.

8. Verify API health, startup from the data root, a representative Catalog
   lookup, and a representative guide query. Check the API container mount is
   read-only and refers to the same project-scoped volume used by the updater.
   API startup requires a valid Catalog snapshot. Images may still be absent and
   text responses should remain available.

9. Run one manual unified refresh and review every module result before scheduling:

   ```bash
   docker compose -f compose.prod.yml -f compose.data.yml \
     run --rm --no-deps -T data-updater \
     refresh-all --workers 8 --image-workers 8
   ```

   The WSL command substitutes `compose.wsl.yml`. Exit code 4 means partial
   completion and requires review; it is not treated as success by systemd.

10. Install the new systemd service and timer, then confirm the next trigger time.
    The timer is daily at 03:00 Asia/Shanghai with `Persistent=false`, so a missed
    time is not replayed. Keep the old guide timer disabled.

### Production systemd installation

After the manual checks above, an authorized operator may install and enable the
production templates:

```bash
sudo install -m 0644 deploy/systemd/dotamind-data-update.service \
  /etc/systemd/system/dotamind-data-update.service
sudo install -m 0644 deploy/systemd/dotamind-data-update.timer \
  /etc/systemd/system/dotamind-data-update.timer
sudo systemctl daemon-reload
sudo systemctl enable --now dotamind-data-update.timer
systemctl list-timers --all dotamind-data-update.timer
```

The service uses `/opt/dotamind` and the production Compose files. Its only
successful nonzero exit is code 3 (the shared update lock was busy); partial
result code 4 remains a failure requiring operator review.

### WSL systemd drop-in

The production unit intentionally contains no workstation path. To use it under
WSL, install the same unit files, then create a local drop-in for the service.
The WSL host has its own `docker.service`, so the production Docker dependency
remains in effect; the drop-in changes only the working directory and command:

```ini
# /etc/systemd/system/dotamind-data-update.service.d/wsl.conf
[Service]
WorkingDirectory=
WorkingDirectory=/home/lip233/code/dotamind
ExecStart=
ExecStart=/usr/bin/docker compose -f compose.wsl.yml -f compose.data.yml run --rm --no-deps -T data-updater refresh-all --workers 8 --image-workers 8
```

Check the local Docker executable path before installing the drop-in. Reload
systemd and inspect the effective service command before enabling its timer. The
WSL Compose file declares project `dotamind`; do not override it for the updater.
Confirm the old guide timer is disabled before enabling the new one.

## Rollback

1. Disable the new timer and wait for any current updater service to finish:

   ```bash
   sudo systemctl disable --now dotamind-data-update.timer
   systemctl is-active dotamind-data-update.service
   ```

2. Remove the data overlay and recreate only the API using its base Compose file:

   ```bash
   docker compose -f compose.prod.yml up -d --no-deps --force-recreate api
   ```

   Use `compose.wsl.yml` for WSL. Without the overlay, API reads its bundled
   Catalog and uses Redis guides when configured.

3. Keep both the `shared-data` volume and Redis data. Do not run
   `docker compose down -v`. If resuming the old Redis guide schedule, first
   confirm the unified timer is disabled and no updater service is running; never
   install both as daily jobs.

The fresh-data WSL deployment, live refresh, API-only recreation, and timer
activation described above have occurred. The first scheduled firing has not yet
been observed, and no production deployment or Redis guide migration is implied.
