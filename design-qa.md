# Startup overlay design QA

## Comparison target

- Source visual truth: the original mock at `C:/Users/10721/.codex/generated_images/01a008c9-5942-7d30-8aca-aad7dae6202e/exec-d9898cd9-a2e2-4bca-a628-5beb2575ad0d.png`, refined by the final requests to remove the cat and keep only the `DotaMind` title.
- Validation: local-browser captures at a 1280 × 720 CSS viewport (density 1) verified both the completed-chat state and the startup state.
- State: desktop chat with grayscale controls, a red Dota 2 watermark, and a red startup icon/progress treatment.
- The final captures verify the requested grayscale controls with red Dota marks; temporary capture files are intentionally not retained in the repository.

## Findings

No actionable P0, P1, or P2 differences against the current grayscale interface with red Dota marks.

- Layout and hierarchy: the red Dota 2 tile remains the visual anchor above the `DotaMind` title and progress line; removing the cat and secondary copy creates a compact, single-title stack.
- Colors and visual tokens: the shell, selection state, primary actions, and focus use grayscale. Dota red is reserved only for the startup icon/progress treatment and the low-opacity central watermark.
- Separation: sidebar and header divider borders remain absent; contrast comes from the grayscale surface hierarchy and soft shadows.
- Watermark: the real `simple-icons` Dota 2 path is centered behind the content at 70% of the main panel height, with a low-opacity red treatment that preserves content legibility.
- Layout: the sidebar header retains its “聊天记录” label and 65 px height. The desktop main area has no header, allowing chat content to use the full available height; mobile-only controls float above content.
- Scroll treatment: the sidebar thread list remains scrollable but hides its visual scrollbar.
- Asset fidelity: no cat sprites or background silhouettes remain in the rendered overlay. The Dota 2 mark is the actual monochrome `simple-icons` path, not an approximate generated logo.
- Empty state: a new chat uses the same real Dota 2 mark in a 150 × 150 px red tile instead of the former `DM` letter badge.
- Copy and controls: `DotaMind` is the only startup copy; the visible skip control has been intentionally removed while `Esc` dismissal remains available.

## Focused interaction check

- During startup, the rendered page contained one Dota 2 badge and no cat image or cat-specific DOM elements.
- No `.startup-overlay__skip` element is rendered.
- `Esc` remains wired to the overlay dismissal path.
- The automatic exit transition completes without a console error.

## Final result

final result: passed
