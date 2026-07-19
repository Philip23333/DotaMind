# DotaMind Progress Snapshot: 2026-07-19

## 14:16 — Deterministic recall-answer removal

- The Controller now applies idempotent normalization to schema-valid recall
  decisions: free-form `answer` is forced to `null` for `quote_user_query`,
  `recall_entity`, and `recall_assistant_summary`, while social answers remain
  unchanged.
- `decision_validate_node` repeats normalization at Graph runtime and writes the
  decision, kind, and tool plan back to state, so custom Controllers cannot
  bypass the rule. Logs record only the response mode, never the discarded
  answer content.
- Historical `basis` validation is unchanged: unavailable Turns, mismatched
  fields, failed Turns, and missing entity matches still return a decision
  validation error. The defense-in-depth error now directly instructs recall
  decisions to use JSON `null` for `answer`.
- The Controller Prompt now distinguishes recall and social decisions: recall
  selects a non-empty basis and lets the server render from validated Turns;
  social uses an empty basis and a textual answer.
- Regression tests cover all three recall modes, preserved social answers,
  idempotence, invalid basis handling, and a single-call case where the model
  says Shadow Fiend but the stored Lina Turn deterministically wins.

### Verification

- Full API suite: `356 passed, 1 warning`; the warning is FastAPI/Starlette's
  upstream `httpx` deprecation notice.
- `uv run ruff check .` passed.
- `uv lock --check` passed.
- `git diff --check` passed with only the repository's existing LF/CRLF
  conversion notices.
- No live DeepSeek/STRATZ network request was run in this phase.
