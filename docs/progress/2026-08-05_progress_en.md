# DotaMind Progress Snapshot — 2026-08-05

## 16:54 — V3.3-2 A1 design contract frozen

### Completed

- Added `docs/design/versions/DotaMind_V3.3-2_design.md`, freezing PostgreSQL/Redis responsibilities, reuse of `RunContext.run_id`, the Run state machine, idempotency and ownership, atomic completion, event allowlists and the browser-level Run Store boundary.
- Defined `DOTAMIND_MAX_CONCURRENT_CHAT_RUNS` as a per-API-worker concurrency limit; because this phase has no independent queue, it does not promise a deployment-wide global limit.
- Defined client disconnect as observer cancellation only; service restart/stale recovery marks Runs `interrupted`, with no LangGraph checkpoint or automatic resume.

### Verified

- A1 only added the design contract and this progress entry; database models, APIs, runtime graph and frontend execution paths were not changed.

### Boundary

- A2-A5 and B-E are not implemented; the design document remains explicitly marked “A1 only”.

## 17:02 — V3.3-2 A2 chat_runs model and migration

### Completed

- Added `ChatRunRow` to the PostgreSQL ORM with Run ID, session/request idempotency, status, fencing, worker, event sequence, heartbeat, cancellation/terminal timestamps and final Turn linkage.
- Added Alembic `20260805_03` with the status CHECK, session/request uniqueness, active-Run partial unique index, unique result-Turn index and lookup indexes.
- Added the `chat_sessions.runs` relationship; deleting a session cascades Runs and deleting a result Turn nulls `result_turn_id`.

### Verified

- A2 code checks and `git diff --check` passed; the Repository and execution scheduler are not implemented yet.

### Boundary

- A3-A5 and B-E are not implemented; `/plan`, `/plan/stream` and frontend behavior remain unchanged.

## 17:18 — V3.3-2 A3 Run Repository

### Completed

- Added the `ChatRunRepository` contract, stable errors, lifecycle DTOs and `PostgresChatRunRepository`.
- Implemented Run creation/idempotent replay, browser ownership, active-Run conflicts, queued→running, heartbeats, cancel requests, terminal closure and stale-Run interruption.
- Added PostgreSQL integration coverage for browser isolation, per-session activity uniqueness, idempotency conflicts, the cancel state machine and stale closure.

### Verified

- `uv run ruff check app`: passed.
- `tests/test_postgres_chat_run_repository.py` is covered against real PostgreSQL and follows the existing skip behavior when `DOTAMIND_TEST_DATABASE_URL` is unset.

### Boundary

- A4 atomic `complete_with_turn()` is not implemented yet; A5 will complete the full Repository regression.
- B-E are not implemented; the existing API and frontend execution paths remain in place.

## 17:32 — V3.3-2 A4 atomic completion

### Completed

- `PostgresChatRunRepository.complete_with_turn()` now locks the Run and session in one PostgreSQL transaction, validates worker/fencing ownership, writes one Turn, updates title/index and closes the Run as `completed`.
- Completion is rejected for `cancel_requested`, terminal Runs and stale fencing; repeating a completed Run returns the existing result without writing another Turn.
- Extended PostgreSQL integration coverage for atomic commit, duplicate completion, Turn uniqueness and fencing rejection.

### Verified

- `uv run ruff check app tests/test_postgres_chat_run_repository.py`: passed.
- `uv run pytest -q tests/test_postgres_chat_run_repository.py`: both tests followed the existing skip behavior because `DOTAMIND_TEST_DATABASE_URL` is not configured.

### Boundary

- A5 will complete the full Repository regression and close Stage A; B-E are not implemented.

## 17:46 — V3.3-2 A5 Stage A regression closure

### Completed

- Added a pure contract test fixing the closed, disjoint active/terminal status sets so later API or Manager code cannot introduce unknown states.
- Updated the Stage A design status to A1-A5 complete; B-E remain explicitly unimplemented.

### Verified

- `uv run ruff check app tests`: passed.
- `uv run pytest -q tests/test_chat_run_contract.py tests/test_postgres_chat_repository.py tests/test_postgres_chat_run_repository.py`: `1 passed, 3 skipped` because `DOTAMIND_TEST_DATABASE_URL` is not set locally.
- `uv run alembic upgrade head`: passed; `uv run alembic check`: `No new upgrade operations detected`.
- `git diff --check`: passed.

### Stage A conclusion

- The PostgreSQL `chat_runs` schema, status DTOs, lifecycle Repository and Run/Session/Turn atomic completion contract are implemented.
- Existing `/plan`, `/plan/stream`, background tasks and frontend execution paths are unchanged; next is B1 preallocated Run IDs.

## 18:02 — V3.3-2 B1 preallocated Run ID

### Completed

- Added internal `internal_run_id` to `AgentRunState`; `run_init_node` reuses it when supplied, while stateless requests still generate UUID v4 when it is absent.
- Added the B1 contract test proving that `RunContext.run_id` exactly matches the preallocated ID.

### Verified

- `uv run ruff check app tests`: passed.
- `uv run pytest -q tests/test_run_init_preallocation.py`: passed.

### Boundary

- B2-B8 are not implemented; `internal_run_id` is not yet wired into ChatRunExecutor or a public API.

## 18:21 — V3.3-2 B2 Redis Run Event Bus

### Completed

- Added the `RunEventBus` contract and `RedisRunEventBus` with one Stream per Run, Lua-atomic sequences, TTL, sequence replay and Redis cancellation notifications.
- Added the `status` runtime event model; stored events accept only the existing allowlist and never store query, history, prompt, tool arguments or raw exceptions.
- Stream/sequence keys use a Run ID hash; the Event Bus accepts an injected Redis client for real integration tests and independent lifecycle management.

### Verified

- `uv run ruff check app tests`: passed.
- Redis integration coverage is included and follows the existing skip behavior when `DOTAMIND_TEST_REDIS_URL` is unset.

### Boundary

- B3 Event Pump, B4 Manager, B5 Graph execution and B6-B8 failure closure are not implemented; the Event Bus is not yet used by an API or background task.

## 18:39 — V3.3-2 B3 Run Event Pump

### Completed

- Added `RunEventPump` and `bind_run_event_pump()`: Graph nodes continue publishing synchronously while a Run-scoped asyncio queue writes to the Event Bus asynchronously.
- The pump supports start, flush, sequence cursor, queue bounds and stable Event Bus failure propagation; the queue must flush before the pump exits.
- Added pure unit coverage for event order, sequence values and non-silent Event Bus failures.

### Verified

- `uv run ruff check app tests`: passed.
- `uv run pytest -q tests/test_run_event_pump.py`: passed.

### Boundary

- B4 Manager, B5 Graph wiring and B6-B8 failure closure are not implemented; the Event Pump is currently driven only by tests.

## 12:06 — V3.3-1 PostgreSQL chat persistence and anonymous browser multi-chat

### Completed

- Added async SQLAlchemy/asyncpg database resources, Alembic configuration and a migration for
  `chat_sessions` and `chat_turns`; PostgreSQL stores the complete user query, public response and
  compact `Turn`.
- Added `PostgresChatRepository` for create/list/transcript/rename/delete, browser ownership,
  fencing claims, idempotent replay/conflict handling and monotonic per-session turn allocation.
- The new persistent request path uses the Redis `SessionStore` for lease/fencing coordination while
  PostgreSQL is authoritative for chat history; new requests do not write turns or public responses
  to Redis.
- Added `/api/v1/chat/sessions` create/list/read/rename/delete endpoints; stateful `/plan` and
  `/plan/stream` require `X-DotaMind-Browser-Id`, `session_id` and `request_id`.
- `apps/chat` now persists a UUID v4 browser identity and active session in localStorage, provides
  create/select/rename/delete multi-chat navigation, and restores messages from the PostgreSQL
  transcript; the existing real NDJSON streaming run card remains in place.
- Added the V3.3-1 design document and synchronized API, architecture and chat-app documentation.

### Verified

- `cd apps/api && uv run alembic upgrade head`: migration `20260805_01` applied successfully.
- PostgreSQL integration test (`DOTAMIND_TEST_DATABASE_URL`): `1 passed`, covering browser
  isolation, transcript, automatic title, rename, idempotent replay/conflict, compact Turn and delete.
- `uv run ruff check app tests`: passed.
- `uv run pytest -q`: `465 passed, 15 skipped`; the existing FastAPI TestClient deprecation warning remains.
- `apps/chat`: `npm run lint` and `npm run build` passed.

## 18:58 — V3.3-2 B4 BackgroundRunManager

### Completed

- Added `BackgroundRunManager`, applying `DOTAMIND_MAX_CONCURRENT_CHAT_RUNS` as a per-API-worker cap; each Run owns an independent asyncio task and execution state.
- Added duplicate Run rejection, shutdown admission control, targeted cancellation, and coordinated worker shutdown; shutdown only notifies the persistence layer through a callback and does not mutate PostgreSQL directly.
- Background task failures are retained in a worker-local failure ledger so detached exceptions are not lost; durable state and cross-worker coordination remain for B5-B7.

### Verified

- `uv run ruff check app tests`: passed.
- `tests/test_background_run_manager.py`: `3 passed`, covering per-worker concurrency slots, targeted cancellation, shutdown, and duplicate submission.
- `git diff --check`: passed.

### Boundary

- B4 establishes worker-local lifecycle management only. Graph execution, the Run Repository, Redis cancellation listening, and HTTP APIs remain in B5-B8.

## 19:22 — V3.3-2 B5 background Graph executor

### Completed

- Added `ChatRunExecutor`, executing a pre-created Run in the order `SessionStore.transaction → PostgreSQL fencing → mark_running → history → AgentGraphRunner → complete_with_turn`.
- `ChatRunExecutionRequest.run_id` is injected into `AgentRunState.internal_run_id`, so `run_init_node` produces the same `RunContext.run_id`; Graph events bind a Run-scoped Event Pump before execution.
- The final Turn is committed atomically in PostgreSQL before Redis `result`/`completed` events are published; Redis/Event Bus failure cannot roll back a committed Turn. Graph errors record stable `execution_error`; cancellation currently closes as `interrupted`, with user-cancel semantics refined in B6.

### Verified

- `uv run ruff check app tests`: passed.
- `tests/test_chat_run_executor.py`: `2 passed`, covering preallocated Run ID, fencing/history ordering, commit-before-terminal-event, and Graph failure closure.
- `git diff --check`: passed.

### Boundary

- B5 provides the background Graph execution loop but does not yet connect Manager cancellation listeners, heartbeat/reconciliation, or the C-stage HTTP API.

## 19:47 — V3.3-2 B6 cancellation and failure semantics

### Completed

- `BackgroundRunManager` now supports an optional Redis cancellation listener: it handles only notifications targeted to the current worker (or broadcast notices), using Pub/Sub to accelerate local `task.cancel()` without treating Redis as the authority.
- `ChatRunExecutor` handles task cancellation by attempting `mark_cancelled()` first; only a PostgreSQL `cancel_requested` state becomes `cancelled`, while other worker cancellation becomes `interrupted`.
- Unhandled Graph exceptions become `failed` with stable `execution_error`; listener failures are consumed and recorded without an in-memory fallback.

### Verified

- `uv run ruff check app tests`: passed.
- `tests/test_background_run_manager.py tests/test_chat_run_executor.py`: `7 passed`, covering worker-target filtering, targeted cancellation, cancellation/interruption mapping, and failure closure.

### Boundary

- B6 does not yet add periodic heartbeat checks, the stale sweeper, restart recovery, or the C-stage public cancel API; those remain in B7/C.

## 20:15 — V3.3-2 B7 heartbeat and stale recovery

### Completed

- Added `RunHeartbeat`, which refreshes PostgreSQL `heartbeat_at` on a configured interval and cancels only the local executor task when the authoritative status becomes `cancel_requested`.
- Added `RunStaleSweeper`, computing a cutoff from `DOTAMIND_RUN_STALE_SECONDS` and using the Repository conditional sweep to interrupt heartbeat-expired `queued/running/cancel_requested` Runs.
- `ChatRunExecutor` can start/stop a heartbeat per Run; `Settings` now exposes per-worker concurrency, heartbeat, stale, and sweeper intervals under the `DOTAMIND_` prefix.

### Verified

- `uv run ruff check app tests`: passed.
- `tests/test_run_recovery.py tests/test_chat_run_executor.py tests/test_config.py`: `21 passed`.
- `git diff --check`: passed.

### Boundary

- B7 provides heartbeat/sweeper internals but does not yet start a supervisor from FastAPI lifespan or implement the C-stage Run API; worker restart scheduling remains for C/E integration closure.

## 20:42 — V3.3-2 B8 Stage B regression closure

### Completed

- Added a Redis Event Bus fail-fast regression: Redis unavailability exposes `unavailable` directly and never falls back to an in-memory event bus.
- Added an observer-disappearance regression: without an HTTP subscriber, the detached Run Event Pump still writes and flushes its events.
- Consolidated focused coverage for preallocated Run IDs, event ordering/replay, concurrency caps, cancellation/failure, and heartbeat/stale components to close the Stage B internal loop.

### Verified

- `uv run ruff check app tests`: passed.
- Stage B focused suite: `14 passed, 1 skipped`; the Redis integration test follows the existing convention and skips when `DOTAMIND_TEST_REDIS_URL` is unset.
- `git diff --check`: passed.

### Stage B conclusion

- Background Runs continue after HTTP observers disappear; PostgreSQL is authoritative for state/Turns while Redis carries replayable events and cancellation notifications. Stage B does not change the existing `/plan` or frontend cutover boundary.

## 21:08 — V3.3-2 C1 Chat Run API contract

### Completed

- Added `chat_run_schemas.py`, freezing create, query, active-Run, event, cancel, and stable-error response models; public responses exclude payload hashes, worker/fencing data, and internal Agent state.
- Added the `chat_run_routes.py` namespace and shared helpers for `X-DotaMind-Browser-Id` parsing, Run DTO mapping, and error-code reasons; concrete endpoints are added in C2-C5.

### Verified

- `uv run ruff check app tests`: passed.
- `tests/test_chat_run_api_contract.py`: `2 passed`.
- `git diff --check`: passed.

### Boundary

- C1 freezes the API/schema/ownership/error contract only; FastAPI endpoint registration, Manager scheduling, and Redis event subscription remain for C2-C5.

## 21:47 — V3.3-2 C2 create Chat Run

### Completed

- Added `ChatRunRuntime`: preallocates a UUID v4, calls `create_or_get_run()` with a payload hash, persists new Runs as `queued`, and submits them to `BackgroundRunManager`.
- Registered `POST /api/v1/chat/sessions/{session_id}/runs`; new Runs return `202`, idempotent replays return `200`, and active/idempotency conflicts use stable `409` errors.
- FastAPI lifespan now constructs the Run Repository, Redis Event Bus, Manager, Executor, and stale sweeper when Redis is configured; without Redis the Run API returns `503 unavailable` and never falls back to an in-memory event bus.
- Dispatch failures close the newly created queued Run as `failed/dispatch_failed` instead of leaving it permanently queued.

### Verified

- `uv run ruff check app tests`: passed.
- `tests/test_chat_run_runtime.py tests/test_plan_route.py`: `13 passed` (with the existing TestClient deprecation warning).
- `git diff --check`: passed.

### Boundary

- C2 covers creation and dispatch only; Run query, active-Run, event replay/subscription, and cancel APIs are C3-C5. The old stateful `/plan` path is not removed yet.

## 22:28 — V3.3-2 C3 Run query and active-Run

### Completed

- Added `GET /api/v1/chat/runs/{run_id}` and `GET /api/v1/chat/sessions/{session_id}/active-run`, enforcing browser ownership and returning `404 not_found` for Runs outside the current browser.
- PostgreSQL chat session list/transcript queries now use an active-Run left join and expose `run_id/status/last_event_sequence/error_code` without N+1 queries.
- Public Run/session DTOs continue to hide payload hashes, worker/fencing data, and internal Agent state.

### Verified

- `uv run ruff check app tests`: passed.
- `tests/test_chat_run_query_routes.py tests/test_chat_run_runtime.py tests/test_postgres_chat_repository.py`: `4 passed, 1 skipped`.
- `git diff --check`: passed.

### Boundary

- C3 does not yet implement Redis Stream subscription, terminal synthesis, or the cancel API; the old stateful `/plan` path remains.

## 23:08 — V3.3-2 C4 Run event subscription

### Completed

- Added `GET /api/v1/chat/runs/{run_id}/events?after=N`: ownership is checked first, Redis Stream entries with `sequence > after` are replayed in sorted/deduplicated order, then `XREAD` waits for more events.
- Each wait timeout emits a heartbeat outside Redis and re-reads PostgreSQL Run state; a terminal PostgreSQL Run with missing Stream entries produces a `transcript_recovery=true` terminal status event.
- Redis event failures end the observer with a stable stream error; HTTP disconnect only exits the generator and never calls `Manager.cancel`.

### Verified

- `uv run ruff check app tests`: passed.
- `tests/test_chat_run_event_routes.py`: `2 passed`, covering ordered replay/terminal close and missing-Redis-event recovery.
- `git diff --check`: passed.

### Boundary

- C4 does not yet expose the public cancel API; event subscription never owns the background task lifecycle, while C5 handles cancellation transitions and Redis notifications.

## 23:52 — V3.3-2 C5 cancel API

### Completed

- Added `POST /api/v1/chat/runs/{run_id}/cancel`; it first calls PostgreSQL `request_cancel()`, then attempts to wake the local Manager and publish a Redis cancel notification.
- Repeated `cancel_requested` requests remain idempotent `202`; terminal Runs return `409 run_terminal`; Redis notification failure never rolls back the durable cancel request, and heartbeat provides eventual discovery.
- The cancel API shares browser UUID v4 ownership and stable error mapping with create/query/event routes.

### Verified

- `uv run ruff check app tests`: passed.
- `tests/test_chat_run_cancel_routes.py tests/test_chat_run_runtime.py`: `5 passed`.
- `git diff --check`: passed.

### Boundary

- C5 does not fabricate a `cancelled` terminal state; the background Executor closes it based on PostgreSQL state. C6/C7 continue stateful-path migration preparation and full API regression.

## 23:58 — V3.3-2 C6 stateful-path migration preparation

### Completed

- Added `apps/chat/src/lib/chat-run-api.ts` with create/get/active/events/cancel clients and NDJSON event parsing using AbortSignal for observer subscriptions.
- Extended shared frontend types for Run statuses, active Runs, status/recovery/heartbeat events, and active Run metadata on session transcript/list responses.
- C1-C5 backend APIs are mounted while stateful `/plan`, `/plan/stream`, and the PlanService PostgreSQL branch remain unchanged, preserving an atomic D-stage cutover boundary.

### Verified

- `apps/chat`: `npm run lint` passed without warnings; `npm run build` passed.
- `uv run ruff check app tests`: passed.
- `git diff --check`: passed.

### Boundary

- C6 adds client/types preparation only and does not change the existing message-send path; the old stateful path is removed only after the D-stage cutover.

## 23:59 — V3.3-2 C7 Stage C API regression closure

### Completed

- Completed focused API coverage for creation, query, active-Run, event replay/terminal synthesis, cancellation, browser ownership, idempotency, and terminal errors.
- Added the terminal-cancel `409 run_terminal` regression and stable reasons for `not_found` and invalid `after`.
- Stage C keeps the old stateful `/plan`, `/plan/stream`, and frontend send path intact, preserving a runnable boundary before the atomic D-stage cutover.

### Verified

- API focused suite: `22 passed` (including the existing TestClient deprecation warning).
- Full `uv run pytest -q`: `491 passed, 20 skipped, 1 warning`.
- `uv run ruff check app tests`: passed.
- `apps/chat`: `npm run lint` and `npm run build` passed.
- `git diff --check`: passed.

### Stage C conclusion

- The backend independently supports Run creation, state queries, event observation, and cancel requests; observer connections do not own task lifetime. The old path is not removed, and the next stage introduces the browser-level Run Store.

## 23:59 — V3.3-2 D1 browser-level Run Store

### Completed

- Added `chat-run-store.ts` reducer: `run_id` is the Run identity and `activeRunIdBySession` indexes each session’s active Run; phase/tool/delta/result/status/heartbeat/recovery events are reduced into UI state.
- Every event validates Run ID, session ID, and strictly increasing sequence; late, duplicate, and cross-session events are discarded.
- Added `ChatRunProvider`, `useChatRun`, and `useSessionLoader`, wired into the root layout; the session loader registers transcript-provided active Runs in the global Store.

### Verified

- `apps/chat`: `npm run lint` and `npm run build` passed.
- `git diff --check`: passed.

### Boundary

- D1 establishes state and recovery entry points only; message sending, subscriptions, switch races, stop controls, and the old stateful API remain for D2-D7.

## 23:59 — V3.3-2 D2 switch sending to Chat Run API

### Completed

- `ChatSessionRuntime` now calls `createChatRun()` before creating runtime pending state, then consumes `subscribeChatRun()` events to produce assistant output.
- Phase/tool/delta/result/status/error events continue mapping into the existing assistant-ui runtime; a failed Run creation leaves no fake runtime pending entry.
- The old stateful `/plan/stream` is no longer the formal chat send entry point, but remains as a D-stage debug/compatibility boundary until final cutover.

### Verified

- `apps/chat`: `npm run lint` and `npm run build` passed without warnings.
- `git diff --check`: passed.

### Boundary

- D2 does not yet recover pending Runs, resume subscriptions from cursors, protect switch races, call the cancel API from Stop, or delete the old stateful code; those remain in D3-D7.

## 23:59 — V3.3-2 D3 pending Run recovery

### Completed

- Session activation reads `active_run`, fetches complete Run metadata, and creates stable `${runId}:user` / `${runId}:assistant` pending message IDs.
- Recovery subscriptions always replay from `after=0`; the reducer rebuilds phase/tool/delta/status/cursor state, and closing the observer only aborts the subscription without cancellation.
- Recovered runtime information is stored in the global Run Store and existing RuntimeInfoCard, so a refresh still shows an in-flight Run.

### Verified

- `apps/chat`: `npm run lint` and `npm run build` passed without warnings.
- `git diff --check`: passed.

### Boundary

- D3 does not yet handle selection-sequence races across simultaneous session switches, Stop/cancel, unread counts, or deletion of the old stateful path.

## 23:59 — V3.3-2 D4 switch-race protection

### Completed

- `activateSession()` now owns `detailsAbortController`, `selectionSequence`, and `requestedSessionId`; a new selection aborts stale detail/Run metadata requests.
- Every detail and active-Run response validates sequence, requested session, and AbortSignal before writing UI state, so late responses cannot overwrite the current chat.
- Switching keeps the sidebar mounted with a right-side loading overlay and never cancels the backend Run.

### Verified

- `apps/chat`: `npm run lint` and `npm run build` passed without warnings.
- `git diff --check`: passed.

### Boundary

- D4 protects detail-loading races; unified subscription abort, Stop/cancel, unread counts, and deletion of the old path remain in D5-D7.

## 23:59 — V3.3-2 D5 Stop and cancel

### Completed

- When assistant-ui Stop raises `AbortError`, the frontend calls `cancelChatRun()` if an `activeRunId` exists; the backend persists `cancel_requested` before waking the worker/publishing its notification.
- The local UI immediately shows the cancelled message while the Run Store registers the backend response; a cancel request failure never fabricates a durable terminal state, and recovery reconciles later.
- Recovery-subscription and switch-detail abort paths never call the cancel API, preserving “disconnecting observation is not cancellation.”

### Verified

- `apps/chat`: `npm run lint` and `npm run build` passed without warnings.
- `git diff --check`: passed.

### Boundary

- D5 does not yet add session-level unread counts, a unified background subscription manager, deletion of the old stateful path, or final browser acceptance.

## 23:59 — V3.3-2 D6 unread counts and polling

### Completed

- The Run Store now tracks `unreadRunCountBySession` with mark-read/mark-unread actions; terminal events in non-current sessions create unread counts that clear on activation.
- ChatSidebar displays per-session unread Run badges; Assistant polls the session list every five seconds to detect background Runs disappearing from active state and mark them unread.
- The current session’s stream still drives RuntimeInfo/Store directly; polling only discovers cross-session state and never replaces the Redis event cursor.

### Verified

- `apps/chat`: `npm run lint` and `npm run build` passed; lint has no warnings.
- `git diff --check`: passed.

### Boundary

- D6 does not remove the old stateful `/plan` path or run the final browser multi-window/disconnect matrix; D7-D8/E close those boundaries.
- A running FastAPI instance passed a real session CRUD smoke test: create, isolated list, rename,
  cross-browser 404 and delete.

### Boundary

- Anonymous identity is scoped to one browser's localStorage; login, cross-device sync, sharing,
  search, attachments, message editing/branching, reconnect, heartbeat and LangGraph checkpointing
  are not implemented.
- Redis still stores coordination metadata required for lease/fencing; PostgreSQL is authoritative
  for new chat transcripts and memory. The old SessionStore interface and repository-less test path
  remain for existing unit-test coverage.
- This change is not committed yet; the pre-existing `.env.example` Redis backend edit was preserved.

## 13:04 — P1 fencing/deletion fixes and P2 frontend experience fixes

### Completed

- Fencing tokens are now allocated strictly monotonically inside a PostgreSQL row-lock
  transaction; Redis/in-memory coordinators provide only the short-lived lock. After Redis key
  loss, natural expiry or an API coordinator restart, the next token remains greater than the
  value persisted by PostgreSQL.
- `commit_turn` still enforces `active_fencing_token`; stale owners are rejected. Real
  PostgreSQL/Redis integration tests cover Redis state cleanup, natural expiry and lock protection.
- Chat deletion now acquires the SessionStore coordination lock before deleting PostgreSQL
  session/turns; it clears only Redis data keys under that lock and releases the lock normally.
  It never removes another owner's active lock. Busy deletion returns `409 chat_busy`, repeated
  deletion remains a stable `404`, and Redis cleanup failure is logged without masking a completed
  PostgreSQL delete.
- The streaming final `result` now optionally includes a session summary. The client updates the
  automatic first-turn title and re-sorts by `updated_at` without reloading turns; manual titles
  remain protected.
- Mobile uses a drawer chat list with open/close controls. Chat management is now a persistent
  “more” menu with touch/keyboard support, Escape handling, focus return, explicit ARIA names and
  delete confirmation instead of hover-only controls.
- Tightened narrow-screen message/composer widths, horizontal overflow and safe-area spacing while
  preserving the desktop layout.

### Verified

- `uv run pytest -q`: `465 passed, 17 skipped`; the existing FastAPI TestClient deprecation warning remains.
- With real PostgreSQL + Redis, `tests/test_postgres_chat_repository.py tests/test_persistent_fencing.py`:
  `3 passed`.
- `uv run ruff check app tests`: passed.
- `apps/chat`: `npm run lint` and `npm run build` passed.
- Real streaming API verification: the final event returned the updated session summary and the
  automatic first-turn title was persisted immediately.
- Browser responsive verification: `390×844`, `393×852`, `768×1024`, and `1280×800` had no
  horizontal overflow; mobile drawer open/close, more menu, Escape close and focus return passed.

### Boundary

- Redis restart itself was not performed during tests; real Redis key deletion and natural expiry
  simulated state loss. PostgreSQL remains authoritative for fencing and chat records.
- Title synchronization is carried by the final stream event; a client-side update failure does
  not affect the already displayed answer.

## 16:12 — Re-validation after interrupted repair

### Verified

- `uv run alembic upgrade head` and `uv run alembic check`: passed.
- With real PostgreSQL + Redis: `tests/test_persistent_fencing.py tests/test_postgres_chat_repository.py`: `3 passed`.
- `uv run ruff check app tests`: passed.
- `apps/chat`: `npm run lint` and `npm run build`: passed.

## 23:59 — V3.3-2 D7 remove the old stateful `/plan` path

### Completed

- `PlanRequest` now accepts only `query` and `game`; public `/plan` and `/plan/stream` reject stateful fields such as `session_id` and `request_id`.
- `/plan` and `/plan/stream` call only stateless `PlanService.run(query, game)`; route-level browser/session/idempotency error mapping and legacy call arguments were removed.
- Removed the old PostgreSQL chat branch from `PlanService`; production multi-turn execution now goes through `ChatRunExecutor` via the Chat Run API, while SessionStore is mounted independently for chat-CRUD deletion coordination.
- Updated plan-route regression tests to freeze the stateless-only input boundary and NDJSON debug stream behavior.

### Verified

- `uv run ruff check app tests`: passed.
- `uv run pytest -q tests/test_plan_route.py tests/test_plan_service.py`: `18 passed`.
- Full `uv run pytest -q`: `488 passed, 20 skipped, 1 warning` (the existing FastAPI TestClient deprecation warning).
- `apps/chat`: `npm run lint` and `npm run build` passed.
- `git diff --check`: passed.

### Boundary

- The repository-less helper left after D7 was removed in D8; formal chat sending, recovery, cancellation and persistence do not pass through `/plan`.
- D8 will run the full backend/frontend regression and final multi-Run contract acceptance; E is not implemented.

## 23:59 — V3.3-2 D8 frontend tests and Stage D closeout

### Completed

- Removed the old `streamDotaMind()` stateful `/plan/stream` request from `apps/chat/src/lib/dotamind-api.ts`; the chat application call surface now uses only the Chat Run API.
- Reduced `PlanService` to `run(query, game)`, removing request-scoped session/idempotency and repository-less stateful branches; ChatRunExecutor remains the direct history/session/request/run_id execution contract.
- Added a minimal Vitest setup and pure `chat-run-store` reducer tests for sequence deduplication, Run/session isolation, concurrent Runs, terminal unread state and session cleanup.
- Retired obsolete PlanService stateful tests while retaining independent idempotency-hash, state-machine, execution-boundary and privacy regressions.

### Verified

- `uv run alembic upgrade head`: passed.
- `uv run alembic check`: `No new upgrade operations detected`.
- `uv run ruff check app tests`: passed.
- Full `uv run pytest -q`: `469 passed, 20 skipped, 1 warning` (the existing FastAPI TestClient deprecation warning).
- `apps/chat`: `npm run test`: `1 file, 3 tests passed`; `npm run lint` and `npm run build` passed.
- `git diff --check`: passed.

### Stage D conclusion

- The browser-level multi-chat Run Store, switch/recovery/cancel/unread behavior and stateless debug boundary are complete; the old stateful chat execution path is removed.
- Stage E still needs real restart/Redis-expiry recovery, browser acceptance matrix and final documentation acceptance.

## 23:59 — V3.3-2 E2 Chat Run observability

### Completed

- Added low-cardinality Chat Run Prometheus metrics for terminal count/duration, event publish/replay, event-bus errors, active subscriptions, cancellation outcomes and stale interruptions.
- Wired metrics into `ChatRunExecutor`, `RunEventPump`, Chat Run event subscriptions, cancel Runtime and the stale sweeper; no `run_id`, `session_id`, query or user text is used as a label.
- Added observability contract assertions that freeze the label sets and prevent high-cardinality identity leakage into monitoring.

### Verified

- `uv run ruff check app tests`: passed.
- `tests/test_observability.py tests/test_run_recovery.py tests/test_run_event_pump.py tests/test_chat_run_executor.py`: `10 passed`.

### Boundary

- E1 recovery components and worker lifespan are present; real PostgreSQL/Redis matrices, browser acceptance and final documentation closeout remain E3-E6.

## 16:39 — Preventing the empty-state flash on chat switching

- The right chat runtime rendered one empty-message frame after remount, briefly showing the “new chat” state; `ChatSessionRuntime` now notifies the parent after mounting before the right-side loading overlay is removed.
- The overlay covers the runtime initialization frame during switching, so the empty Welcome state is not exposed while the sidebar remains mounted.
- `apps/chat`: `npm run lint` and `npm run build`: passed.

## 16:35 — Partial refresh on chat switching

- Switching sessions no longer replaces the whole chat page with a full-screen loading state; the left `ChatSidebar` stays mounted while only the right transcript/runtime area shows a loading overlay and remounts after the data arrives.
- Initial page bootstrap still uses the full-screen loading state; sidebar actions are temporarily disabled during a switch to avoid competing in-flight selections.
- `apps/chat`: `npm run lint` and `npm run build`: passed.

## 16:29 — Visual indicator for pinned chats

- Pinned chats now show a Pin icon before the title in the left sidebar; unpinned chats do not. Title truncation, the action menu and keyboard focus behavior remain unchanged.
- `apps/chat`: `npm run lint` and `npm run build`: passed.
- `git diff --check`: passed.
- Full `uv run pytest -q`: `478 passed, 4 failed, 1 warning`. The four failures are concentrated in existing tests that require a successful `natural_language_answer` without an LLM provider (`test_agent_plan_debug.py`, `test_agentic_graph.py`, `test_plan_service.py`); they do not exercise the PostgreSQL/Redis fencing, deletion-lock protection, or frontend changes in this repair. The full regression must not be reported as passing.

### Conclusion

- The P1 fencing-token and deletion-lock fixes, plus the P2 title synchronization, mobile drawer and chat-action menu changes, are present in the working tree and their focused regression tests pass.
- Full-suite convergence still requires a configured LLM provider or a fake provider injected into the existing natural-language tests; this is outside the persistence-repair code change.

## 16:25 — Chat action menu and pinning

### Completed

- Added a document-level `pointerdown` outside-click listener to the “more” menu; clicking outside the menu, its trigger, or a menu item closes it immediately while preserving Escape and focus-return behavior.
- Added durable `is_pinned` storage and index to `chat_sessions` with Alembic migration `20260805_02`; pinning does not change the conversation activity `updated_at`.
- `PATCH /api/v1/chat/sessions/{session_id}` now accepts `{ "is_pinned": true|false }`; list responses and streaming session summaries expose pin state. Pinned sessions sort first, followed by unpinned sessions ordered by recent activity.
- Added “Pin chat/Unpin chat” to the frontend action menu; the state survives a page refresh.

### Verified

- `uv run alembic upgrade head` and `uv run alembic check`: passed.
- PostgreSQL + Redis focused tests: `3 passed`.
- `uv run ruff check app tests`: passed.
- `apps/chat`: `npm run lint` and `npm run build`: passed.
