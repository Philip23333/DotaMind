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
