# DotaMind Progress Snapshot — 2026-08-04

## 16:42 — Mainline and historical version reference consolidation

### Completed

- Fast-forwarded remote `master` without force to the V3.2 completion commit `0040c00` and made it
  the GitHub default branch.
- Created and pushed three annotated version tags: `v3.0.0 -> 5251258`,
  `v3.1.0 -> f7779cb`, and `v3.2.0 -> 0040c00`.
- Removed local and remote development branches already covered by the mainline:
  `feature/v3-functional-loop`, `feature/v3.1-agentic-loop`, `codex/langgraph-migration`, and
  `codex/v3.2-agent-runtime-foundation`.
- Per the user's decision, removed the unmerged `feature/llm-rebuild` CROO prototype branch without
  creating an archive tag or merging its unique commit into `master`.
- Refreshed `origin/HEAD` and remote-tracking references; both local and remote now retain only
  `master` as the active branch.

### Final state

- Active branch: `master -> 0040c00`, tracking `origin/master`.
- Historical releases are retained by the immutable `v3.0.0`, `v3.1.0`, and `v3.2.0` tags.
- This operation changes only Git references and progress documentation; accepted V3.2 runtime behavior
  remains unchanged.

## 20:10 — V3.3 chat frontend prototype

### Completed

- Added the standalone Product Design prototype at `prototypes/v3.3-chat/` on branch `v3.3`, following
  the user's selected first visual direction: dark tactical analysis styling, conversation sidebar,
  central chat stream, and evidence inspector.
- Implemented new conversation, conversation selection, sidebar collapse/restore, evidence inspector
  toggle, follow-up submission, analysis/loading state, and completed-answer state, with responsive
  layouts for desktop, 900px tablet, and 390px mobile widths.
- Generated three project-local hero portrait assets with the built-in Image Gen tool and used Inter
  plus Phosphor Icons for typography and standard UI icons; prototype data is explicitly labelled as
  non-live demonstration data.
- Added `design-qa.md`, desktop/tablet/mobile captures, and same-size combined comparison evidence.
  After two P1/P2 correction passes against the selected visual, final design QA is `passed`.

### Verified

- `npm run build`: succeeded.
- `npm run test:sites`: 4 passed.
- Browser verification: evidence and sidebar toggles, new conversation, message submission, loading,
  and completed states passed; the target desktop viewport has no page overflow and the browser
  console has no errors or warnings.

### Boundaries

- This phase is a standalone runnable high-fidelity frontend prototype. It is not yet connected to
  `/api/v1/plan` and does not implement real conversation persistence, streaming responses, or deployment.
- The deleted legacy `apps/web` was not restored; the existing `/debug/plan` internal debugger and
  V3.2 backend behavior remain unchanged.

## 20:27 — V3.3 chat prototype removal

### Completed

- Per the user's decision, removed the entire `prototypes/v3.3-chat/` directory created in this
  round, including prototype source, generated hero portraits, QA screenshots, the design QA report,
  dependencies, and build output.
- Stopped the prototype's local Vite preview process and removed the empty `prototypes/` parent
  directory afterward.

### Final state

- Branch `v3.3` remains available, and the three previously generated visual directions remain as
  references for a later redesign.
- The working tree no longer contains a V3.3 frontend prototype; `/debug/plan` and V3.2 backend
  behavior are unchanged.

## 21:00 — V3.3 minimal assistant-ui chat frontend

### Completed

- Added `apps/chat/`, a Next.js 16 / React 19 application using assistant-ui `LocalRuntime` for the
  minimal message list, Markdown, composer/send, cancellation, copy, and regeneration interactions.
- Added a thin API adapter that calls only the existing `POST /api/v1/plan`: each page session creates
  one UUID v4 `session_id`, every request creates a fresh UUID v4 `request_id`, and answer summaries,
  recommendations, claims, limitations, and non-success statuses are rendered as readable messages.
- Removed the OpenAI / AI SDK route bundled with the assistant-ui initializer and deleted unused
  attachment, tool-call, and reasoning components; no second model call or backend runtime was added.
- Updated the root README, chat application README, and technical architecture documentation with the
  startup path, single-API boundary, and current non-goals.

### Verified

- `npm run lint`: passed.
- `npm run build`: passed, including the Next.js production build and TypeScript checks.
- Real-browser verification: the first message returned a DotaMind answer, and a second follow-up reused
  the server session and referenced the prior turn; the 1280px viewport had no horizontal overflow and
  the browser console had no errors or warnings.

### Boundaries

- The current API returns one complete JSON response, so the client shows a real loading state and does
  not simulate token streaming.
- This slice does not include message restoration after refresh, a conversation list, server streaming,
  attachments, or user authentication; refreshing the page creates a new session.
- `/debug/plan` remains the internal runtime debugger; this change does not modify V3.2 API or Agent
  Runtime behavior.

## 21:47 — V3.3 true streaming and compact runtime information

### Completed

- Added `POST /api/v1/plan/stream`: the same `PlanRequest` now returns NDJSON phase, tool,
  natural-language answer-delta, and single terminal events over POST; the existing `/api/v1/plan` does
  not bind a stream publisher and retains its existing response behavior.
- Bound a safe request-scoped `ContextVar` publisher before creating the background `PlanService.run()`
  task. Graph, tool, and natural-answer nodes publish allowlisted fields only. A tool shows running only
  after validation immediately before handler entry; reuse, reference resolution, pre-dispatch blocking,
  and handler failure all produce a safe terminal event.
- The OpenAI-compatible Provider reads upstream SSE with `stream: true` incrementally and accumulates a
  complete summary for the existing Critic flow; direct replies and deterministic structured replies do
  not simulate token streaming.
- Converted the chat LocalRuntime adapter to an async generator that parses NDJSON across network chunks
  and accumulates provisional prose. It replaces that prose with the public `result` response; failures,
  cancellation, and failed review do not retain the provisional content.
- Added a per-message aggregate runtime card showing “analyze → use tools → organize answer → review
  evidence”, Chinese tool names, and statuses. It remains expanded while running, automatically folds on
  success, and remains open on failure or cancellation.
- Updated API, architecture, and chat documentation with the NDJSON protocol, event privacy allowlist,
  reconnect non-goals, and the requirement to disable reverse-proxy buffering for this path.

### Verified

- `apps/api/.venv/Scripts/python.exe -m ruff check app tests`: passed.
- `apps/api/.venv/Scripts/python.exe -m pytest tests/test_plan_route.py tests/test_agentic_answer.py tests/test_agentic_recovery.py tests/test_agentic_runtime.py -q`: `74 passed`.
- `apps/api/.venv/Scripts/python.exe -m pytest -q`: `465 passed, 14 skipped` (with the pre-existing FastAPI TestClient deprecation warning).
- In `apps/chat`, both `npm run lint` and `npm run build` passed.

### Boundaries

- This first phase does not provide reconnect, heartbeat, background recovery, cross-page session history,
  or individual default tool cards.
- Only the natural-language synthesizer may show genuine deltas before the Critic with a “generating,
  pending review” marker. The final public response is the only formal answer; Critic or execution
  failure withdraws the provisional prose.

## 21:55 — Official 7.41e patch snapshot

### Completed

- Used the existing offline sync script to read Valve's official Dota 2 datafeed directly and added
  `apps/api/app/data/patches/7_41e.json`.
- The generated schema v1 snapshot records the 7.41e release time `2026-07-30T07:00:00Z` and 151
  changes: 2 general, 31 regular-item, 5 neutral-item, 3 enchantment, and 110 hero changes.
- The sync script also checked Valve's official hero list; it remains at 127 heroes and produced no
  effective change to the committed hero snapshot.
- Updated the patch-tool latest-version assertion from 7.41d to 7.41e. Runtime requests still read only
  reviewed local snapshots and never access the official site from the request path.

### Verified

- Assertions passed for the JSON structure, required change fields, polarity enum, and 151-record count;
  `load_patch("latest")` correctly returns 7.41e.
- `uv run pytest tests/test_agentic_patch_tools.py -q`: `4 passed`.
- `uv run ruff check tests/test_agentic_patch_tools.py scripts/sync_game_data.py app/integrations/patch_notes.py`: passed.

### Boundaries

- Polarity retains the existing conservative rule-based classification; ambiguous official text remains
  `neutral`, with no manual rewriting introduced.
- Valve's lists do not resolve names for some neutral-item/enchantment IDs or entity `1961`. As in 7.41d,
  the snapshot retains `neutral_<id>` or numeric targets and the official text instead of masking the
  upstream gap with manual mappings.
