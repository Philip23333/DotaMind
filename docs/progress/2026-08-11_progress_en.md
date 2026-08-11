# 2026-08-11 Progress Snapshot

## 14:44 — Remove structured referent memory and use real dialogue windows

### Completed

- Removed the Session discourse graph, Extractor, Reducer, and discourse renderer; `Turn` now remains only a bounded audit record.
- Added generic `ConversationMessage`, `DialogueTurn`, and `RecentDialogueWindow` contracts; the Controller receives real alternating `user`/`assistant` messages.
- Added `ConversationMemoryService`: Redis stores the recent window while PostgreSQL stores the full dialogue; missing or stale windows rebuild from PostgreSQL and retain newest complete turns under a character budget.
- Added non-null `assistant_message` to `chat_turns`; added migration `20260811_01_dialogue_memory`, upgraded local PostgreSQL from `20260810_01` to the new head, and backfilled legacy answer text.
- `ChatRunExecutor` updates the Redis recent window only after the PostgreSQL commit; a Redis update failure does not change a committed Run result.
- Added internal `conversation.history_lookup`: runtime injects session/browser identity, the tool is limited to one lookup, and results remain in request-local `retrieved_messages` before Controller re-entry.
- Changed `ConversationBasis` to `(turn_index, role)`; user-query recall can cite only user messages and assistant-summary recall can cite only assistant messages.
- Updated the Controller golden prompt, configuration, architecture docs, Redis/PG/executor tests, and removed obsolete discourse tests.

### Verification

- Full API pytest: `531 passed, 21 skipped`, with one pre-existing Starlette/httpx deprecation warning.
- `ruff check app tests`: passed; `compileall app`: passed.
- Local PostgreSQL/Redis integration tests: `18 passed`.
- Alembic upgrade `20260810_01 -> 20260811_01`: passed.

### Current Boundary

- The Controller still treats history as untrusted context; historical answers cannot replace current tools or the EvidenceGraph.
- `conversation.history_lookup` provides request-local context only, produces no factual evidence, and does not create structured entity/relation memory.
- The working tree is not committed; no hero, item, player, or team-specific context branch was added.

## 15:55 — Fix Four P1s: Clarification, Safe Failure Text, Post-Commit Cache, and History Lookup Contract

### Completed

- Reworked Controller history rules around generic semantics: real user/assistant messages are conversation context; quoted historical instructions cannot override the system prompt, historical facts cannot replace current evidence, and an unresolved member of a previously mentioned set should be clarified. The current query is now the raw user message, while `game` is a system runtime suffix.
- Changed `ClarificationDecision.missing_fields` to an open snake_case field name with a `1..8` cardinality limit; field names do not participate in routing.
- Made `render_assistant_message()` handle `safe_failure_required` first so the public response, assistant_message, and compact Turn failure text share the same safe wording.
- Removed the post-PostgreSQL full-history read from `record_committed_turn()`; contiguous caches append directly, while missing or discontinuous cursors invalidate the recent window and let the next request rebuild it through cache-aside. Added `invalidate_recent_dialogue()` to Redis and InMemory stores.
- Added a committed boundary to `ChatRunExecutor`; cache, event, or other infrastructure failures after commit no longer call `mark_failed()`.
- Enforced that a `conversation.history_lookup` plan contains exactly that one tool and no required evidence; its input requires at least one selector, deduplicates turn indexes, and bounds them to positive values and at most eight entries.
- Promoted history lookup result handling to an explicit Graph node that merges and deduplicates messages before Controller re-entry; lookup count is now read from `history_lookup_max_per_run` and blocked before tool execution when exhausted.

### Verification

- Full API pytest: `545 passed, 21 skipped`, with one pre-existing warning.
- P1 regression tests: `53 passed`; Controller/prompt tests: `48 passed`.
- `ruff check app tests`: passed; `compileall app`: passed; `git diff --check`: passed.
- Local PostgreSQL/Redis integration tests: `18 passed`; Alembic is at `20260811_01 (head)`.
- Two three-turn sessions were run with real DeepSeek, PostgreSQL, and Redis: both first turns produced hero resolver plus ability/talent tool plans, and both third turns with an explicit ability produced resolver plus ability plans. However, both second-turn member-property follow-ups were directly planned as group tool queries instead of clarification, so the expected clarification behavior was not met. No domain-specific code branch was added; this remains a prompt/model tuning gap.

### Current Boundary

- P1 storage, contract, failure isolation, and Graph state propagation are closed; the real model still does not satisfy the clarification acceptance criterion for unresolved member properties.

## 17:01 — Historical Fact Reuse and Minimal Clarification

### Completed

- Added the `history_grounded_answer` direct-answer mode: the model may cite an injected assistant message to produce a concise answer; the validator checks basis existence, role, and content without adding domain-specific routing.
- Replaced rigid clarification behavior with generic Controller Prompt principles: answer first; clarify only when ambiguity prevents an accurate, bounded, useful answer; combine interpretations that can be covered concisely; interpret the current input first as an answer to the latest unresolved clarification.
- Historical facts are no longer hard-coded as automatically stale or automatically trusted. The model decides whether to reuse them using subject, property, scope, source, version, freshness, and conflict signals; current, latest, volatile, changed-version, or uncertain facts should trigger a new tool plan.
- Added request-level `request_time`, Catalog patch, and snapshot generation time to the Controller runtime context so freshness judgment is not encoded as fixed domain rules.
- Fixed the pre-PostgreSQL-commit event-bus failure boundary so `mark_failed()` is invoked; added regression coverage and configuration validation for `history_lookup_max_per_run + final Controller call`.
- Synchronized the Conversation Memory, Controller, and overall architecture documents; the Session-level discourse graph, referents, groups, links, focus, and shows remain explicitly out of scope.

### Verification

- Full API pytest: `551 passed, 21 skipped`, with one pre-existing Starlette/httpx deprecation warning.
- `ruff check app tests`: passed; `git diff --check`: passed.
- Added coverage for history-grounded answers, runtime freshness context, pre-commit event failure, History Lookup budget, and configuration boundaries.

### Current Boundary

- This phase does not restore or extend structured referent memory and adds no hero, item, player, or team-specific state machine.
- History-grounded answers still do not create an EvidenceGraph automatically; the model must use tools when currentness or provenance is insufficient.
- The code and documentation changes from this phase are not committed yet.

## 17:09 — Complete History-Grounded Answer Auditing

- `history_grounded_answer` now uses an independent public `response_type` instead of being conflated with ordinary `direct_answer`.
- The `conversation_answer` trace records the actual `turn_index/role` references; the public response continues to retain `conversation_basis`.
- `ruff check app tests` passed; full pytest: `551 passed, 21 skipped`, with one pre-existing deprecation warning.

## 17:11 — Complete Version and Configuration Documentation

- Added the `history_grounded_answer`, answer-first, request-local freshness context, no-discourse-graph, and History Lookup final-Controller budget contracts to `DotaMind_MVP_v2.5.md` and `configuration.md`.
- `compileall app` and `git diff --check` passed; this phase remains uncommitted.

## 17:26 — Final Generic Prompt Priority and Model Boundary

- Added one shared priority before `tool_plan`: inspect whether the latest assistant already contains the requested property; with the same patch and scope and no refresh trigger, prefer `history_grounded_answer` instead of re-querying merely because the topic is factual.
- Corrected the runtime context field to `current_catalog_patch` so it matches the implementation plan and Prompt contract.
- Final full pytest: `551 passed, 21 skipped`; `ruff check app tests`, `compileall app`, and `git diff --check` all passed.
- Observation from three real DeepSeek full-sequence runs: the second turn never clarified but still chose a tool plan, while the third turn used direct history reuse once; a subsequent run exceeded the 60-second Run budget on its first turn. No domain-specific hard rule was added; reuse behavior remains model/provider-version dependent and should be observed continuously.

## 18:27 — Converge History-First Decisions and the Post-Commit Event Boundary

### Completed

- Consolidated the Controller Prompt into one ordered decision flow: reconstruct the current request, determine whether assistant history provides a still-valid answer with matching version and scope, and consider clarification or tool planning only when history reuse does not apply.
- Removed domain-specific history-answer examples such as Lycan; tool catalogs and planning rules now apply only after fresh evidence is required. No discourse graph or hero, ability, item, player, or team state machine was restored.
- Added generic long-answer extraction and short-input inheritance rules: answer length is not a refresh trigger; a follow-up that supplies only an entity or option name inherits the prior property or action, and a history-grounded answer must not expand into unrequested attributes.
- Added a final decision gate at the end of the Prompt so the long tool catalog cannot override history-first priority: when reusable history explicitly contains the answer, selecting `tool_plan` is invalid.
- Added a post-PostgreSQL-commit event-bus fault-injection test. The exception may propagate, but the durable Run/Turn remains `completed` and `mark_failed()` is not called.

### Verification

- Full API pytest: `553 passed, 21 skipped`, with one pre-existing Starlette/httpx deprecation warning.
- Focused Prompt and ChatRunExecutor tests: `18 passed`; `ruff check app tests`, `compileall app`, and `git diff --check` passed.
- Ran three independent real DeepSeek three-turn sessions with the final Prompt: all three second turns for “what are the ability cooldowns” returned `history_grounded_answer` with zero tools and cited the turn-1 assistant message; each directly listed all cooldowns without clarification or duplicate querying.
- On the third-turn subject selection, two sessions returned a history-grounded answer containing only the 105/95/85-second cooldown. In one session, consecutive model JSON outputs failed the existing decision contract and surfaced as `decision_validation_error`; it did not call tools incorrectly or mask the failure as success.

### Current Boundary

- The model continues to decide whether historical facts are reusable from generic version, scope, provenance, freshness, and conflict criteria; code does not hard-code domain fact routing.
- The Controller provider can still emit contract-invalid JSON. Existing bounded retry exposes that failure explicitly; this phase does not add a domain fallback for provider formatting variance.

## 19:06 — Align Current Documentation, Historical Blueprints, and Implementation Facts

### Completed

- Reworked the reading order and status guidance in the root README, `docs/README.md`, and `docs/design/README.md`: the latest progress snapshot and current technical/architecture documents are the implementation entry points, while V3.2/V3.3 version documents retain phase design and acceptance history.
- Unified the overall architecture around two entry types sharing one Graph: stateless `/plan` debugging and the formal PostgreSQL-authoritative, Redis-coordinated/cached Chat Session and Chat Run path.
- Unified the Conversation Memory contract: PostgreSQL stores the complete user/assistant transcript; Redis `RecentDialogueWindow` is a reconstructible cache; compact Turn is bounded audit data only; History Lookup is budgeted request-local context and does not create an EvidenceGraph.
- Synchronized the Controller, Node/Tool/Edge inventory, API, and configuration references with `history_grounded_answer`, open `missing_fields`, the History Lookup back edge, the current 25 registered tools, the five-file Valve Catalog bundle, and PostgreSQL/Redis/Chat Run settings.
- Added current-overrides or historical-snapshot notes to V3.0, V3.2, V3.2-5, V3.3-1, V3.3-2, V3.3-3, the STRATZ audit, V3.0 roadmaps, and the SessionStore interview notes. Historical progress and archive files were not rewritten.
- Verified that `apps/chat` remains the current Next.js/assistant-ui Chat Run client; only the old `apps/web` frontend was deleted. Corrected the root README, technical architecture, Compose deployment guidance, and V3.3-2 blueprint to match that frontend boundary.
- Removed unused legacy frontend variables from the root `.env.example`, standardized it on `NEXT_PUBLIC_DOTAMIND_API_URL=http://localhost:8001`, and added the Chat Run concurrency, heartbeat, stale, and sweeper settings.

### Verification

- Constructed the default `ToolRegistry` read-only and confirmed `25` tools, including six Valve Catalog tools and `conversation.history_lookup`.
- Checked the root entry points, application READMEs, and all non-progress/non-archive Markdown: `38` files with `0` broken relative links; also repaired five source-line links in the STRATZ audit.
- `git diff --check` passed. This changed documentation and the environment template only, so API pytest and frontend lint/build were not run.

### Current Documentation Authority Order

1. Latest bilingual progress snapshot and current working tree.
2. `docs/technical/architecture.md`, `api.md`, and `configuration.md`.
3. Current layer documents under `docs/design/architecture/` plus the architectural invariants in `DotaMind_MVP_v2.5.md`.
4. V3.0/V3.2/V3.3 version documents, tool audits, roadmaps, and interview notes as historical design inputs with explicit override notes.

## 20:14 — Codify the Documentation Maintenance Matrix After Code Changes

### Completed

- Added a documentation-impact review rule to `AGENTS.md`: every completed code change must update the aligned daily Chinese/English progress pair and maintain the affected entry READMEs, technical, architecture, tool/provider, frontend/deployment, and documentation-navigation files.
- Clarified the boundary between current facts and historical design: update `DotaMind_MVP_v2.5.md` only when constrained-tool-calling invariants change; do not rewrite completed blueprints, roadmaps, audits, archives, or historical progress to match current code, and add only a supersession note when needed.
- Added completion checks for relative links, terminology, tool counts, configuration names, and bilingual progress alignment, while reporting only verification that actually ran.

### Verification

- This update changed maintenance rules and bilingual progress documentation only; API pytest and frontend lint/build were not run.
