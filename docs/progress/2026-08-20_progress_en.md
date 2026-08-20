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
