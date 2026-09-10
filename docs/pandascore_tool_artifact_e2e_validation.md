# Tool → Artifact → Model End-to-End Validation

Date: `2026-09-10`  
Branch: `codex/model_behavior_optimization`  
Runtime revision: `df23b03`

## Scope

This run exercised the real vNext model, registered tools, PandaScore adapters,
Artifact externalization/read/grep, and final model answers. It did not call
the legacy controller or bypass the Agent Runtime. Ten scenarios produced eleven
model turns, including one two-turn Artifact reuse conversation.

Trace files are stored locally under:

```text
apps/api/tests/vnext/testResult/e2e_*.json
```

No credentials are written to the traces or this report.

## Acceptance table

| Case | User question | Tool sequence | Artifact | Steps / calls | Final answer | Detours / failure reason |
| --- | --- | --- | --- | ---: | --- | --- |
| E1 | TI 2026 是什么赛事 | `league.search → series.search×3 → tournament.search → series.teams → artifact.read×15` | created | 9 / 21 | Correct | Repeated series resolution and unrelated stage/team enrichment; one oversized artifact item read recovered by narrower reads |
| E2 | TI 2026 有哪些阶段 | `league.search → series.search → tournament.search → artifact.read×11 → match.search(upcoming) → match.search(running)` | created | 7 / 16 | Correct | Two lifecycle match calls were unnecessary for the requested tournament list |
| E3 | TI 2026 有哪些参赛队 | `league.search → series.search×2 → artifact.read → series.teams` | created | 5 / 5 | Correct | One broad `series.search(league_id, limit=50)` was unnecessary after year narrowing |
| E4 | Team Spirit 在 TI 2026 小组赛战绩 | `league.search → team.search → series.search → tournament.search → artifact.read×4 → match.search(tournament_id=21545, team_id=1669)` | created | 8 / 9 | Correct | No material detour; canceled match was explicitly separated from 5 finished matches |
| E5 | TI 2026 Playoffs 总决赛结果 | `league.search → series.search×3 → tournament.search → artifact.read → match.search(tournament_id=21698, lifecycle=past) → artifact.read` | created | 7 / 8 | Correct | Repeated series discovery before narrowing to tournament 21698 |
| E6 | TI 2021 Playoffs 历史参赛阵容 | `league.search → series.search×3 → tournament.search×2 → artifact.read×16` | 3 created | 11 / 23 | Correct | Repeated searches; four oversized artifact reads failed and were recovered through narrower reads |
| E7 | Team Spirit 当前阵容 | `team.search` | none | 2 / 1 | Correct | None |
| E8 | Larl 当前在哪支队 | `player.search(name=Larl)` | none | 2 / 1 | Correct | None |
| E9 | TI 2026 Series 全部比赛 | `match.search(series_id=10828) → series.search(id=10828) → artifact.read×22` | created | 14 / 24 | Correct | Redundant series lookup and two overlapping Artifact pagination passes |
| E10a | 获取 TI 2026 全部比赛 | `series.search → match.search → artifact.read×12` | created | 14 / 14 | Correct | Required bounded pagination; no provider error |
| E10b | 继续统计 Team Spirit 胜负 | `artifact.read → artifact.grep → artifact.read → artifact.grep → artifact.read×4` | reused | 4 / 8 | Correct | First literal grep for `"id":1669` returned no matches; semantic grep for `Spirit` recovered; no new PandaScore call |

## Evidence by layer

### Tool selection and ID propagation

- All model calls used declared tools and valid arguments.
- The expected IDs were eventually propagated correctly: `4106 → 10828 →
  21545/21698 → match filters`, and `Team Spirit → 1669`.
- No case used `match.search(name="TI")` as a substitute for the
  League → Series → Tournament hierarchy.
- Direct `series_id=10828` input was respected for the large Match cases.

### Artifact and bounded observation

- Large Tournament, Match, and historical roster responses were externalized;
  small Team/Player responses stayed inline.
- Artifact reads correctly returned bounded pages and exposed opaque refs for
  continuation.
- E6 produced four expected `invalid_arguments` responses when the model asked
  for oversized items; the model then narrowed to participant-level reads and
  completed the answer.
- E10b reused the exact Artifact ref from E10a and issued no new `esports.*`
  call. The final tally was 9 wins, 3 losses, and 1 canceled match.

### Stopping behavior

Stopping is the main weakness in this run. E1, E2, E3, E5, E6, and E9 all made
calls that were not required after the relevant ID had already been resolved.
The clearest example is E2, where `match.search(lifecycle=upcoming)` and
`match.search(lifecycle=running)` were used only to infer that the tournaments
had ended. E9 also performed two overlapping Artifact pagination passes.

### Final synthesis

All eleven turns reached a final answer. The answers preserved the requested
current-versus-historical distinction, kept canceled matches separate from
finished results, and did not expose provider anomalies (all observed
PandaScore SearchResult anomaly lists were empty in this run).

## Attribution

| Layer | Result | Evidence |
| --- | --- | --- |
| Tool contract | PASS | No invalid `esports.*` arguments or provider-tool failures |
| ID propagation | PASS | League/Series/Tournament/Team IDs were reused correctly |
| Artifact/context | PASS with recovery | Bounded reads and cross-turn reuse worked; E6 had recoverable budget errors |
| Model routing | REVIEW | Repeated broad searches and optional enrichment in E1/E2/E3/E5/E6/E9 |
| Stopping | REVIEW | Unnecessary lifecycle checks and duplicate Artifact reads |
| Final synthesis | PASS | All requested answers completed with source-backed IDs, scores, rosters, or current state |

## Overall conclusion

The complete Tool → Artifact → Model path is operational for the tested
scenarios. The next optimization target is model behavior rather than DTO or
provider transport: preserve resolved IDs, avoid repeated discovery once scope
is fixed, and use one Artifact pagination strategy instead of overlapping reads.
