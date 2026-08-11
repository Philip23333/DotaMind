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
