# DotaMind Progress Snapshot (2026-07-28)

## 18:55 — V3.2-5 Redis Session Store implementation and pending verification

### Implementation

- Added `RedisSessionStore` beside `InMemorySessionStore` under the same `SessionStore`
  interface; `PlanService` does not branch by backend.
- Redis keys use namespaced session/request hashes. Compact Turns, RequestRecords, and public
  responses use strict schema-v1 JSON envelopes. The request Hash field uses a request-key hash
  for lookup, while the record payload hash detects query/game conflicts.
- Implemented atomic Lua acquire/renew/release, fencing tokens, append, claim/replay/conflict,
  `complete_request_with_turn`, and failed takeover. Session and request records follow TTL/
  capacity rules, and in-progress records are excluded from GC.
- Added `memory|redis` backend configuration, a Store factory, FastAPI lifespan, Redis startup
  PING, shutdown close, and HTTP 503 `session_store_error`; runtime Redis errors never fall back
  to memory.
- Docker Compose Redis now uses AOF with `appendfsync everysec`. API and design documents explain
  that Redis Server restart recovery still depends on persistent volumes and deployment policy.

### Tests and verification

- Added schema round-trip/corrupt-schema, backend-factory, 503 mapping, and real-Redis cross-
  Store integration test coverage. Integration tests require `DOTAMIND_TEST_REDIS_URL`, use a
  random namespace, and never run `FLUSHDB`.
- Verified: `uv run ruff check .` passes; `uv run pytest -q` reports
  `445 passed, 3 skipped, 1 warning`; `uv lock --locked` and `git diff --check` pass.
- The three skips are real Redis integration tests. `docker compose up -d redis` could not run
  because the local Docker daemon is stopped, so real Redis acceptance has not run and V3.2-5
  must not be marked completed yet.

### Explicit boundaries

- API/worker rebuild recovery requires reconnecting to the same Redis data. Redis Server restart
  durability is not guaranteed by the application alone; it depends on AOF/RDB, fsync/save
  policy, and persistent volumes.
- This phase adds no business tools, Graph nodes/edges, stateless idempotency, Redis Cluster/
  Redlock, or V3.2-6 fault injection and unhandled-Attempt sealing.

## 19:03 — Local Redis acceptance and empty-array JSON correction

### Acceptance

- Local Docker now runs the project Redis service (`redis:7-alpine`, host
  `127.0.0.1:6379`), and `redis-cli ping` returns `PONG`.
- Real Redis cross-Store integration tests ran with
  `DOTAMIND_TEST_REDIS_URL=redis://127.0.0.1:6379/15`: `3 passed`, covering fencing/Turn order,
  completed replay/conflict, and rebuilt-store recovery.
- The subsequent normal full regression reports `445 passed, 3 skipped, 1 warning`; the three
  skips occur only because that command has no Redis test environment variable, while the real
  Redis acceptance command has already passed. `ruff` and `git diff --check` pass.

### Correction

- Real Redis testing showed that Redis Lua `cjson` conflates empty arrays and empty objects.
  Append/complete scripts now atomically replace only `turn_index` in Python-validated canonical
  JSON, preserving the `[]` schema semantics for `resolved_entities` and `missing_fields`.

## 21:04 — V3.2-5 Redis data-integrity corrections

### Corrections

- RequestRecord public responses no longer pass through Lua `cjson` decode/encode. Python strictly
  reads and builds completed/failed canonical JSON; Lua only validates lock/owner, assigns
  `turn_index` atomically, and writes the JSON. Replays therefore preserve empty arrays such as
  `missing_fields`, `tool_results`, and `runtime.attempts`.
- Claim now strictly reads the current RequestRecord and resolves replay/conflict first. Capacity
  eviction runs only for a new record, so a same-key retry cannot delete its own completed record
  and execute again when capacity is full.
- Begin, complete, and fail strictly deserialize RequestRecords. Unknown schema versions, missing
  fields, and extra fields become `data_invalid` before a Turn is written.
- The renewal interval is now `min(lock_lease_seconds, session_ttl_seconds) / 3`, so an active
  transaction refreshes short Session TTLs before data expires and preserves history plus monotonic
  turn indexes.

### Verification

- Real Redis integration coverage is now nine tests, including public-response empty-array replay,
  replay at full capacity, active short-TTL transactions, and corrupt RequestRecord rejection in
  begin/complete/fail paths.
- Verified: full pytest with `DOTAMIND_TEST_REDIS_URL=redis://127.0.0.1:6379/15` reports
  `455 passed, 1 warning`; normal pytest without the variable reports
  `446 passed, 9 skipped, 1 warning`. `ruff check .`, `uv lock --locked`, and `git diff --check`
  pass.
