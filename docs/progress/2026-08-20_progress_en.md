# 2026-08-20 Progress Snapshot

## 15:05 — Chat empty state and full-height content area

### Completed

- Removed the top-level `DotaMind` and “Dota 2 智能分析助手” copy. The desktop main area no longer reserves a top header, so chat content receives the full height.
- Restored the icon-labelled “聊天记录” sidebar title. The mobile sidebar trigger and runtime-error message now float over the main area and do not consume content height.
- Each entry to the chat page starts with a new empty thread instead of restoring the last selected localStorage session.
- Replaced the empty-state `DM` letter block with the real `simple-icons` Dota 2 SVG mark in a fixed 150 × 150 px red tile.

### Verification

- `apps/chat`: focused `npx eslint` passed; `npm test` reported 10 passed (5 files); `npx tsc --noEmit` passed; `npm run build` passed.
- Local-browser verification confirmed zero top headers, one “聊天记录” title, a rendered 150 × 150 px empty-state Dota icon, and no “Dota 2 智能分析助手” copy.

### Known boundaries

- The startup overlay still keeps its independent `DotaMind` title; this change removes only the post-entry main-area title.
- Stored chat history, pin state, and transcripts were not deleted and remain manually accessible from the sidebar.

## 13:58 — Footer ICP registration

### Completed

- Kept only the “鄂ICP备2026044062号-1” ICP registration number at the chat-page footer, linking to the MIIT registration lookup site, and removed the former disclaimer copy.

### Verification

- The user explicitly requested no tests or build for this minimal visual adjustment.

## 14:12 — Persistent answer copy button

### Completed

- Moved the AI-answer copy button out of message document flow and positioned it in the existing gap below the answer, so hover cannot push answer content.
- Removed `autohide`: completed AI answers show the copy button by default, while answers still being generated continue to hide the action.

### Verification

- `apps/chat`: `npx tsc --noEmit` passed.

## 15:10 — Series-wide game details and cross-source Valve ID chain

### Completed

- `pandascore.resolve_match_games` returns every game actually exposed by the PandaScore Fixture for a uniquely identified series when no game number is supplied; an explicit game number still selects one game, and unexposed games are not fabricated.
- `dota.resolve_valve_matches` batch-consumes the PandaScore competition/game contexts and applies strict OpenDota league, team, time, duration, game-position, and winner matching per game, returning Valve Match IDs and per-game mapping evidence.
- `opendota.match_details` combines result, ten-player scoreboard, parse coverage, and draft lookup and accepts Valve Match ID lists only; PandaScore Series/Match/Game IDs are no longer declared as directly referenceable downstream paths.
- The Controller Prompt and Tool Catalog explicitly state the `PandaScore → Valve Match ID → OpenDota` chain. Genuine `ambiguous_*`, `not_found`, and `insufficient_signals` statuses remain explicit; no Checkpoint, retry, closest-match selection, or alternate-source fallback was added.
- Runtime `max_tool_calls_total` increased from 8 to 16; batch tools keep up to five games within a fixed tool chain.

### Verification

- API focused set: 90 passed; API full suite: 613 passed, 21 skipped, 1 warning.
- `uv run --project apps/api ruff check apps/api/app apps/api/tests` passed; `git diff --check` passed.
- `apps/chat`: `npm test` 10 passed; `npm run lint` passed; `npm run build` passed.

### Known boundaries

- Cross-source league, team, and match ambiguity remains explicit; Checkpoint-based user clarification is not included in this phase.
- The OpenDota detail batch accepts at most five Valve Match IDs; missing BP or parse data reports actual coverage and never fabricates evidence.

## 14:15 — Latest-answer bottom spacing

### Completed

- Increased the message-list end padding by one line so the latest AI answer's copy button keeps stable space above the fixed composer.

### Verification

- Only a Tailwind spacing-class adjustment; no tests or build were run.

## 14:21 — TI quick prompt

### Completed

- Focusing the composer displays a “本届TI最新战况” quick-prompt button above it; the button hides when the input loses focus or while an answer is running.
- Clicking the button writes and directly sends “本届TI最新战况” through the existing composer. Its pointer-down handler preserves input focus so the entry does not collapse before the click.

### Verification

- `apps/chat`: `npx tsc --noEmit` passed.
- Local-browser verification confirmed the quick button is visible exactly once after focusing “消息输入框”; no real query was sent.

### Known boundaries

- The current implementation provides one fixed prompt for an ongoing TI. It does not dynamically derive prompts from an event calendar or external state.

## 14:23 — Limit the quick prompt to new chats

### Completed

- The “本届TI最新战况” entry appears with composer focus only when a new chat has no messages; existing chats do not show it.
- After the first message is sent in a new chat, the non-empty message list automatically removes the entry.

### Verification

- `apps/chat`: `npx tsc --noEmit` passed.

## 16:42 — Coverage serialization and cross-source reference Prompt fix

### Completed

- `pandascore.resolve_match_games` now serializes `ResolvedMatchGames.coverage` item by item as a list; populated results return a list of dictionaries and empty results return `[]`, with the old single-object/`None` path removed.
- Added an async handler-level regression test covering two coverage rows, empty coverage, two games, two `resolution_inputs`, and transport `aclose()`.
- Added four exact cross-source reference mappings for the example `competition`, `games`, `valve_matches`, and `details` call IDs to the Controller Prompt, explicitly stating that the Tool Catalog already declares them compatible; the no-guess, no-closest-candidate, and no-fallback rules remain.
- Bumped `controller.base` from `v4` to `v5` and regenerated the UTF-8/LF golden fixture; Validator, ToolDefinition, Graph, retry budget, Checkpoint, and ambiguous behavior were unchanged.

### Verification

- Coverage focused set: 20 passed.
- Prompt/Controller focused set: 59 passed.
- API full suite: 616 passed, 21 skipped, 1 warning.
- `uv run --project apps/api ruff check apps/api/app apps/api/tests` passed; `git diff --check` passed.

### Known boundaries

- Planning validation with the real `AgentController` and a fixed chain plan for all three IW/TS phrasings still triggers the existing empty-dict placeholder validation for `dota.resolve_valve_matches.competition`; Validator and tool contracts were intentionally left unchanged, and no live upstream request was made.
- The IW vs TS Valve Match ID mapping failure remains outside this repair.
