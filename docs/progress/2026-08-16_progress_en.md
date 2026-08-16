
## 13:42 — P2.2.1 default edition and historical-year query fix

### Completed

- Controller rules now state that a named recurring competition does not need clarification for a missing year; the resolver is called without `year`. Explicit years are preserved, while a genuinely missing competition/team/player subject still returns clarification.
- `pandascore.resolve_competition` now describes the latest-edition behavior and says not to ask solely because the edition year is missing.
- `PandaScoreCompetitions.list_series(year=...)` sends `filter[year]` only for an explicit year; the resolver builds eligible rows by year before name ranking and main-event/qualifier disambiguation.
- Existing active → latest historical → nearest future behavior is preserved; a missing explicit edition remains `not_found` and never falls back to another year.

### Live integration

- Independent API on port 8002: `现在TI的最新战况如何？` and `The International 最新战况如何？` both produced `tool_plan` with no `year`; `TI 2025 最新战况如何？` produced `year=2025`; `现在最新战况如何？` returned clarification.
- Live execution confirmed Series `10828` / year `2026` for the no-year case and Series `9555` / year `2025` for the explicit historical case; downstream `pandascore.list_matches` had `handler_entered=true`. The isolated API was stopped; 8001 was not modified.

### Boundaries

- No Controller decision validator, intent route, historical fallback, fixed year, or Series ID was added; Runtime and frontend failure presentation remain unchanged.

### Final verification

- `apps/api/.venv/Scripts/python.exe -m pytest -q`: 612 passed, 21 skipped, 1 warning.
- `apps/api/.venv/Scripts/python.exe -m ruff check app tests`: passed.
- `apps/chat`: `npm test -- --run` passed 10 tests in 5 files; `npm run lint` passed; `npm run build` passed.

## 14:05 — Chat startup animation and pixel-cat mascot

### Completed

- `apps/chat` now has a full-screen `StartupOverlay`: the red primary tile uses the Dota 2 monochrome SVG path from `simple-icons`, layered with a project-owned Siamese pixel sprite instead of an approximate generated mark.
- The overlay sits outside the existing Chat Runtime; it fades out after about 1.4 seconds without creating a Chat Run, calling a backend API, or changing session/thread state.
- Users can dismiss it with “Skip animation” or `Esc`; `prefers-reduced-motion` receives only an instant transition.

### Verification

- `apps/chat`: `npm run lint` passed; `npm test` 10 passed; `npm run build` passed.
- Local browser verification covered the startup overlay SVG, pixel sprite, automatic fade-out, and the Skip animation interaction; the console had no errors.
- `design-qa.md`: the side-by-side source/implementation review passed after removing a magenta chroma-key fringe from the pixel sprite.

### Known boundaries

- The animation currently appears on every full page load; it does not persist a first-visit-only marker.
- No Chat Run API, server runtime, or existing chat behavior changed.

## 14:07 — Remove the startup cat mascot

### Completed

- Removed the Siamese pixel sprite, its background silhouette, and the associated local asset from the startup overlay. The red tile with the monochrome Dota 2 SVG from `simple-icons` remains as the sole primary icon.
- Startup duration, fade-out, “Skip animation”, `Esc`, and reduced-motion behavior are unchanged. No Chat Run, backend API, or session-state behavior changed.

### Verification

- `apps/chat`: `npm run lint` passed; `npm test` passed 10 tests; `npm run build` passed.
- The local browser confirmed zero cat layers and a visible Dota 2 SVG tile during startup. After “Skip animation”, zero overlays remained and the console had no errors.
- `design-qa.md` now records the final vector-only icon visual QA.

### Known boundaries

- The animation still appears on every full page load; it does not persist a first-visit-only marker.

## 14:14 — Simplify startup text

### Completed

- Removed the icon subtitle and the “正在加载战局洞察” loading status; `DotaMind` is now the only visible text within the startup overlay.
- Kept the Dota 2 SVG tile, progress line, automatic fade-out, “Skip animation”, `Esc`, and reduced-motion behavior. No Chat Run, API, or session-state behavior changed.

### Verification

- `apps/chat`: `npm run lint` passed; `npm test` passed 10 tests; `npm run build` passed.
- The local browser confirmed that the active startup overlay text is `DotaMind` and both removed subtexts are absent.
- `design-qa.md` now contains the final title-only startup screenshot and side-by-side review.

## 14:21 — Dota 2 dark-red interface theme

### Completed

- Removed the startup overlay’s top-right “Skip animation” button; automatic fade-out and `Esc` dismissal remain available.
- Unified the main interface and sidebar background, card, border, input, focus, and primary-action tokens around a dark brown, Dota-red, and warm-white palette while preserving the existing layout and chat behavior.

### Verification

- `apps/chat`: `npm run lint` passed; `npm test` passed 10 tests; `npm run build` passed.
- The local browser confirmed no skip button after startup, with readable copy across the dark-red chat area, sidebar, message bubble, and input.
- `design-qa.md` now records the dark-red main interface and no-skip-button QA.

## 14:29 — Refine dark-red chat layout

### Completed

- Lifted the main message area from the `background` to the lighter `card` surface, with the composer further lifted to `popover`; the dark-red palette, warm-white copy, and existing interactions remain unchanged.
- Kept the sidebar thread list scrollable while hiding its visible scrollbar.
- Set the main header to 65 px to match the sidebar header’s rendered height, aligning both content starting positions.

### Verification

- `apps/chat`: `npm run lint` passed; `npm test` passed 10 tests; `npm run build` passed.
- The local browser confirmed 65 px main/sidebar headers, zero visible sidebar scrollbar width, normal startup exit, and no console errors.
- `design-qa.md` now records the final lifted surfaces, hidden scrollbar, and aligned layout QA.

## 14:36 — Light main panel and Dota 2 watermark

### Completed

- Switched the main message region to a warm-white surface and the composer to a lighter surface; foreground and muted text within that region now use dark brown for contrast.
- Added the real Dota 2 SVG path from `simple-icons` as a low-opacity central watermark. It is fixed at 70% of the content area height, ignores pointer events, and does not affect scrolling or input.
- The dark-red sidebar and header shell, plus existing message and runtime behavior, remain unchanged.

### Verification

- `apps/chat`: `npm run lint` passed; `npm test` passed 10 tests; `npm run build` passed.
- The local browser confirmed a 0.70 watermark-to-main-panel height ratio, readable copy on the light surface, normal startup completion, and no console errors.
- `design-qa.md` now records the final warm-white main panel and watermark visual QA.

## 14:44 — Grayscale interface with Dota-red emphasis

### Completed

- Switched the sidebar, header, main region, and composer to layered light-gray and near-white surfaces. Tonal contrast and soft shadows remain, with no hard divider borders.
- Reserved Dota red for the selected thread, send button, focus ring, and low-opacity Dota 2 watermark. Copy, borders, message surfaces, and remaining interface tokens are now grayscale.

### Verification

- `apps/chat`: `npm run lint` passed; `npm test` passed 10 tests; `npm run build` passed.
- The local browser confirmed zero sidebar/header border widths, the intended grayscale hierarchy and red emphasis, and no console errors.
- `design-qa.md` now records the final grayscale interface visual QA.

## 14:53 — Grayscale controls with red Dota marks

### Completed

- Returned selected states, send buttons, focus rings, and other interaction emphasis to grayscale.
- Restored the original red treatment for the startup Dota 2 tile/progress line and the low-opacity main-panel Dota 2 watermark. The remaining grayscale hierarchy, border-free separation, and layout are unchanged.

### Verification

- `apps/chat`: `npm run lint` passed; `npm test` passed 10 tests; `npm run build` passed.
- The local browser confirmed red startup and watermark marks, a dark-gray send button, and no console errors.
- `design-qa.md` now records the final grayscale interface with red Dota marks.
