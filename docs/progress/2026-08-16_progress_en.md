
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
