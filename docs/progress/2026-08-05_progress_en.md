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
