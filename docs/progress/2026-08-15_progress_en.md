# 2026-08-15 Progress Snapshot

## 11:10 — P-15 Controller conversation-recall example debiasing

### Completed

- Replaced the Controller prompt's fixed `conversation_recall -> context_missing` JSON example with a neutral `context_missing` field shape and removed the copyable “当前会话中没有足够的历史信息” failure text.
- Preserved the `ContextMissingDecision` output shape (`kind`, `intent`, and `reason`) without adding keyword routing, fixed intent branches, deterministic recall templates, or validators.
- Updated the Controller golden prompt fixture and added assertions preventing the fixed `conversation_recall` mapping and Chinese failure text from returning to the system prompt.
- The current default Controller system prompt is 33,718 characters and 512 lines, with SHA-256 `b8b6f18f1bd2a51076af73d6c789e004fe3796523630d8fa049254ac7606d427`.

### Verification

- `tests/test_agentic_prompts.py`: 12 passed; focused Ruff checks passed.
- Ran six scenarios three times each (18 real samples) through isolated durable Chat Run sessions against a temporary port-8002 API instance loaded from the current source. Every session was deleted with HTTP 204; the temporary API was stopped and its port was closed.
- Before the change: 4/18 `direct_answer`, 14/18 `context_missing`; after the change: 14/18 `direct_answer`, 4/18 `context_missing`.
- After the change, “what was my previous question,” “what did you just answer,” and “which two heroes did I ask about” each passed 3/3. Generic “what did I just ask” passed 1/3, while both two-question phrasings passed 2/3.

### Known boundary

- Removing the misleading example materially improved meta-conversation recall but did not fully close the issue; generic user-question recall can still incorrectly return `context_missing`.
- P-15 remains partially improved. A follow-up should evaluate the smallest positive decision hint against the same real matrix without introducing deterministic Chinese-keyword branches.

## 11:36 — P-15 explicit recent-conversation rule experiment and rollback

### Experiment

- Temporarily added an explicit conversation rule stating that messages already present between the system and current user message are available conversation, and that `context_missing` is invalid and `conversation.history_lookup` unnecessary when the requested content appears there.
- Ran seven scenarios three times each (21 isolated durable Chat Runs) against a temporary port-8002 API loaded from the experimental source. The added scenario used the exact observed wording “我刚才问的什么”.

### Results

- Both generic phrasings (“我刚才问了什么” and “我刚才问的什么”) passed 0/3; explicit previous-question recall passed 2/3; “which two questions” passed 0/3.
- “List my two questions,” assistant-answer recall, and two-hero recall each passed 3/3.
- The 18 scenarios shared with the prior matrix produced only 11/18 `direct_answer`, below the 14/18 result after removing the negative example; the added exact-wording scenario was another 0/3.

### Decision and verification

- The rule provided no verified benefit and duplicated existing history rules, so it was rolled back from source, test assertions, and the golden fixture. The final code retains only the neutral `context_missing` shape change from 11:10.
- After rollback, `tests/test_agentic_prompts.py`: 12 passed. Every temporary session was deleted with HTTP 204; the temporary API was stopped and port 8002 was closed.
- Further synonymous history-availability reminders should not be added. A follow-up must reassess the responsibility boundary between `context_missing`, `conversation.history_lookup`, and model decision-making.

## 12:10 — P-15 conversation-context result destination and empty-lookup summary

### Completed

- Reduced the Controller responsibilities for supplied messages, `conversation.history_lookup`, and `context_missing` to three definitions: supplied request messages are available conversation context; lookup only adds older messages and is not Dota evidence; `context_missing` applies only after considering supplied messages and any completed lookup.
- Added `ToolDefinition.result_destination` with `evidence` and `controller_context` values. Graph routing, ControllerDecision validation, and Registry consistency checks now use that field; tool-name comparisons for `conversation.history_lookup` were removed.
- After a successful `controller_context` tool, messages merge into request-local `retrieved_messages` and a minimal `controller_context_summaries` entry is retained. An empty lookup now appears in the next Controller system input as `{"tool":"conversation.history_lookup","status":"completed","matched_turns":0}`.
- Narrowed the lookup ToolDefinition description to capability only. `result_destination` remains a runtime contract and is not added to every rendered tool prompt entry.
- Updated the Controller golden fixture, current architecture, Controller, Conversation Memory, Tool, node inventory, and Prompt-refactor review documents. The current default Controller system prompt is 33,734 characters and 514 lines, with SHA-256 `0b24cc98e928e6db22006aacfef36b95b1432f6677f87d1ec8bbfac5c8fbf6e2`.

### Verification

- `tests/test_history_lookup.py tests/test_controller_decisions.py tests/test_agentic_prompts.py -q`: 29 passed.
- `tests/test_agentic_contracts.py tests/test_agentic_registry.py -q`: 52 passed.
- Focused Ruff checks passed; `git diff --check` passed with only the existing CRLF conversion warnings.

### Known boundary

- This change covers the Prompt and context-result flow only. The durable Chat Run matrix was not rerun against a real LLM, so P-15 model-level stability still needs the same scenario-set retest.
- `conversation.history_lookup` is currently the only tool declaring the `controller_context` destination; the budget configuration remains named `history_lookup_max_per_run`.

## 12:22 — P-15 real retest after the structural fix

### Results

- Retested the prior failure scenarios through isolated durable Chat Run sessions against a temporary port-8002 API loaded from the current worktree.
- After “你有什么工具可用”: `我刚才问的什么` passed 0/3, `我刚才问了什么` passed 0/3, and `我上一个问题是什么` passed 0/3.
- After both “你有什么工具可用” and “你有什么功能”: `我刚才问过哪两个问题` passed 0/3.
- Overall: 0/12 `direct_answer` and 12/12 `context_missing`. Every recall request used one Controller call and did not execute history lookup.
- The first sample's public transcript clearly contained the complete prior user/assistant turn. In one two-question sample, the failure reason even identified the two historical topics (“available tools” and “features”) but still selected `context_missing`.

### Empty-lookup path

- Two additional requests explicitly required `conversation.history_lookup` for absent older content. Both completed the tool and entered a second Controller call.
- Both second Controller calls planned lookup again, hit `history_lookup_max_per_run=1`, and surfaced `execution_error` instead of the expected `context_missing`.
- The empty-result summary therefore closes the runtime state-loss gap, but the current model does not reliably adopt the intended terminal meaning. The repeated-lookup budget terminal mapping is a newly exposed secondary issue.

### Cleanup and conclusion

- All test sessions were deleted. The temporary port-8002 API was stopped, its listener closed, and its temporary log directory removed; the existing port-8001 service was untouched.
- P-15 remains an open P0. The next step is to revisit the decision contract and model behavior rather than assume the Prompt simplification solved the issue.

## 14:10 — First-phase match tools and PandaScore free-plan inventory

### Completed

- Used the temporary PandaScore token only in a process environment: `/dota2/series`, `/dota2/tournaments`, and upcoming/running/past Fixture lists returned 200; TI 2026 is Series 10828 and Group Stage is Tournament 21545.
- Added the PandaScore transport, competition/Fixture/Game normalization models, and the OpenDota single-match integration; registered `pandascore.resolve_competition`, `pandascore.list_matches`, `pandascore.resolve_match_game`, `opendota.match_summary`, and `opendota.match_draft`.
- Added Bearer authentication, page-size limits, short caching, rate-limit header capture, 401/403/429/non-JSON/timeout mapping, and `DOTAMIND_PANDASCORE_TOKEN` configuration. The token was not written to the repository.
- Added match evidence extraction and Answer source-boundary rules: PandaScore Fixture facts and OpenDota Valve/Replay facts remain separately attributed; `detailed_stats` is not `has_parsed`; an empty draft produces no evidence.
- Updated the Controller golden fixture, registry catalog, Tool/architecture/node inventories, READMEs, configuration documentation, and the PandaScore API inventory.
- With the five tools added, the current Controller system prompt is 37,163 characters and 571 lines, with SHA-256 `dbba108230c07fc322e2be582c324b9ac2729c0e0e1e92b2df0c3e8e986b4675`.

### Verified boundaries

- Known sample `pandascore_match_id=1631694` and game one `pandascore_game_id=738652` resolve from the free Fixture data; team order is irrelevant and a multi-game series without a game number is ambiguous.
- A Game row's `match_id` is the PandaScore parent Match ID, not Valve `match_id`; `GET /dota2/games/738652` returned 403. `resolve_match_game` therefore returns `pending_valve_match_id` without fabricating a mapping, scraping a page, or bypassing plan access.
- OpenDota `8943244303` was live-checked with ten players, parse version 22, and 24 draft rows; normalization returns result, scoreboard, parse coverage, and draft.

### Verification

- `tests/test_pandascore_transport.py tests/test_pandascore_domains.py tests/test_agentic_pandascore_tools.py tests/test_agentic_opendota_match_tools.py`: 17 passed.
- `tests/test_agentic_registry.py tests/test_agentic_contracts.py tests/test_agentic_evidence.py tests/test_agentic_prompts.py`: 75 passed.
- `uv run ruff check app tests`: passed.

### Known limitations

- The free PandaScore Fixture cannot currently map a PandaScore Game to a Valve match ID. A user-supplied Valve ID or permissioned upstream data is required; the first phase does not hide this gap behind a successful result.
- This phase adds no endpoint, structured match output contract, timeline/event/log data, STRATZ fallback, database synchronization, or frontend.

## 18:21 — Phase 2 cross-source Valve single-match mapping

### Completed

- Added `dota.resolve_valve_match` and the declared chain
  `pandascore.resolve_competition -> pandascore.resolve_match_game ->
  dota.resolve_valve_match -> opendota.match_summary/match_draft`.
- Added OpenDota `/leagues` and `/leagues/{league_id}/matches` integration,
  `CrossSourceMatchResolutionPolicy` (default 1,800-second start tolerance and
  5-second duration tolerance), and the `inferred_cross_source` mapping model.
- The resolver uniquely matches league name plus year, reuses the existing team
  resolver, and applies hard unordered team-ID, start-time, duration, series-game
  position, and winner-consistency filters. Zero/multiple candidates, league/team
  ambiguity, and missing signals remain explicit statuses; no weighted or closest
  fallback is used.
- Changed `resolve_match_game` mandatory evidence to
  `match_identity` plus `pandascore_game_identity`; added `data.resolution_input`
  without an inferred Valve ID. OpenDota summary/draft accept resolver references
  and expose `data.match.match_id` as a compatibility alias.
- Added cross-source mapping/league/tool tests and technical documentation; updated
  the Controller catalog, Answer attribution rules, Tool/node inventories, READMEs,
  and configuration documentation.

### Live boundaries

- With the current `.env` token: TI 2026 is Series 10828 / Tournament 21545;
  Match 1631694 / Game 738652 still has native PandaScore `valve_match_id=null`.
- OpenDota live data contains league 19719, series 1130066, and Valve match
  8943244303, but `/teams` returns two equally scored “Nigma Galaxy” candidates
  (10136357 and 7554697). Under the strict `ambiguous_team` rule, the live chain
  does not silently select 10136357.
- Consequently, the known sample's unique `resolved` live smoke did not pass because
  of upstream team-catalog ambiguity. A sanitized unique-team fixture verifies the
  resolved path. No manual Valve table, plan bypass, or page scraping was added.

### Verification

- Focused cross-source/tool/OpenDota/PandaScore/registry/contract/evidence/prompt
  collection: 92 passed.
- `uv run --project apps/api pytest apps/api/tests -q`: 595 passed, 21 skipped, 1 warning.
- `uv run --project apps/api ruff check apps/api/app apps/api/tests`: passed.
- Git-tracked files were scanned; the PandaScore token does not appear in source,
  fixtures, documentation, or test output.

### Explicit non-goals

- No new API endpoint, timeline/event/log data, STRATZ fallback, automatic replay
  parsing, database mapping table, webpage scraping, paid PandaScore detail call, or
  intent routing was added.

## 19:12 — P2.1 league-participation disambiguation for duplicate teams

### Completed

- Kept the public `resolve_team()` semantics unchanged. Only the cross-source
  `ValveMatchResolver` now queries the existing
  `OpenDotaTeams.get_matches(team_id)` for globally ambiguous candidates.
- Team Matches are filtered by exact `leagueid == target OpenDota league ID`;
  `league_name` is diagnostic-only and never participates in the authoritative
  decision.
- Exactly one candidate participating in the target league resolves with
  `league_participation`; zero returns `no_candidate_in_target_league`, and more
  than one returns `multiple_candidates_in_target_league`. Both remain
  `ambiguous_team`; no rating, activity, match-count, or candidate-order guess is used.
- Team audit fields are uniform: direct resolution records
  `global_team_identity`; league disambiguation records `target_league_id`,
  `league_match_count`, and up to five `sample_match_ids`. Successful mappings add
  `team_league_participation` without changing tools, output paths, or evidence kinds.

### Live sample smoke test

- Using the current PandaScore-normalized Series 10828 / Match 1631694 / Game 738652
  and live OpenDota: Nigma candidate 10136357 has eight exact `leagueid=19719`
  records, 7554697 has none, and OG resolves uniquely to 2586976.
- Actual result: `resolved`, Valve `8943244303`, OpenDota league `19719`, series
  `1130066`; start-time delta 115 seconds, duration delta 0, candidate_count 1.

### Verification

- `test_cross_source_match_resolution.py`: 14 passed, covering the duplicate-directory
  topology, zero/multiple candidates, similar league names with the wrong leagueid,
  no Team Matches call for a unique team, upstream error propagation, and final-match
  uniqueness.
- Removed one stale Controller test assertion that contradicted the already-committed
  P-13 dynamic capability catalog; no Controller Prompt or golden fixture was changed.
  The P2.1 full suite is 602 passed, 21 skipped, 1 warning; Ruff passed.

### Boundaries

- Team Matches only disambiguates team identity; it cannot become the final Valve
  match. The final ID still requires unique unordered teams, time, duration, game
  position, and winner hard filters from league matches.
- No webpage scraping, scoring selection, manual Valve mapping, fallback, or new tool
  was introduced.

## 19:05 — P-13 Controller capability source consolidation

### Completed

- Removed the fixed `Supported in this development version` capability list from
  the Controller system prompt. It duplicated the dynamic ToolRegistry catalog and
  had not been updated for the new PandaScore/OpenDota competition and match tools.
- `Direct-answer rules` now require capability questions to derive capabilities
  from the currently rendered tool catalog and summarize them by user-facing task
  area. Internal tool names are listed only when explicitly requested, and
  unregistered capabilities must not be claimed.
- Added one Chinese capability-summary example for presentation style only. It is
  not a fixed capability catalog or intent route; its content remains subordinate
  to the current ToolRegistry.
- The default Controller system prompt is now 38,169 characters and 578 lines,
  SHA-256
  `6aeddc428335bc04b516eb8c91ea28b4173a44a437e74652eb09ae0c98518f50`.
- Recorded P-05 as deferred because no stable failure is currently reproduced;
  P-15 remains open but further changes are paused.

### Verification

- `tests/test_agentic_prompts.py -q`: 14 passed.
- `ruff check app/agentic/prompts/controller_rules.py tests/test_agentic_prompts.py`:
  passed.

### Unchanged boundaries

- No ToolDefinition, tool-call ordering, ControllerDecision schema, Answer Prompt,
  EvidenceGraph, API behavior, or intent routing changed.

## 20:15 — P-16 Controller source boundary for new Dota facts

### Problem and fix

- LunaMax live testing confirmed that simple hero descriptions, complete ability
  lists, and named-ability questions could return `direct_answer` with
  `tool_results=[]`. Catalog capabilities were registered, so the failure was in
  Controller selection of `tool_plan`, not the Catalog chain or Answer.
- The Controller now states that model knowledge is not factual evidence for a
  Dota `direct_answer`. When the requested facts are absent from the current
  message/reusable conversation and registered tools can provide them, the
  decision must be `tool_plan`.
- Narrowed “do not re-query solely because the topic is factual” to facts already
  explicit and reusable in the current message or conversation. The same source
  validity is stated under `Direct-answer rules`.
- Added one fresh-fact counterexample based on the reproduced hero/ability
  failures. It requires `tool_plan` without prescribing Catalog tool names,
  arguments, call order, or intent routing.
- The default Controller system prompt is now 39,037 characters and 592 lines,
  SHA-256
  `fc2b55d016225b9da2d53c47bef23822c3e7225169afb3b3acff6c18f75e22a3`.

### Verification

- `tests/test_agentic_prompts.py -q`: 14 passed.
- `ruff check app/agentic/prompts/controller_rules.py tests/test_agentic_prompts.py`:
  passed.
- Against an isolated temporary port-8002 API loaded from the current working
  tree, “what kind of hero is Beastmaster” selected `tool_plan` 3/3 with
  `resolve_hero` + `dota.hero_attributes` + `dota.hero_abilities`. One complete
  Monkey King ability-list query and one named Boundless Strike query both used
  `resolve_hero` + `dota.hero_abilities`.
- The temporary port-8002 API was stopped. The existing port-8001 process did not
  reliably hot-reload the current Prompt, so its old-Prompt results were excluded
  from final acceptance.

### Unchanged boundaries

- No ToolDefinition, ArgContract, Validator, ControllerDecision schema, Catalog
  handler, EvidenceGraph, Answer Prompt, API behavior, or runtime data changed.
