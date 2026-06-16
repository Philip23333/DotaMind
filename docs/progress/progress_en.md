# MetaMind Implementation Progress

> Last updated: 2026-06-16  
> Audience: human developers + future Agents taking over this project  
> Current focus: the v2.1 experimental path runs end-to-end; LLM is currently wired only into Analyzer meta_report hero insights.

## Project Overview

MetaMind is a composable Dota2 esports intelligence agent. It turns patch notes, match data, and pro team performance into verifiable, callable, eventually paid meta-analysis reports.

The target architecture is still `v2.1`: 3 Agents + 2 Tools + Critic loop.

Design doc: `docs/design/MetaMind_MVP_v2.1.md`

## Current Facts For Handoff Agents

Trust this section before README or older milestone notes.

1. The backend currently has two coexisting paths.
2. The stable legacy services still exist: `MetaReportService`, `PatchImpactService`, `TeamReportService`, `ClaimVerificationService`.
3. The v2.1 experimental entrypoint is: `POST /api/v1/query/experimental`.
4. The v2.1 experimental entrypoint is not yet a full LLM-agent system.
5. The only module that currently makes real LLM calls is `AnalyzerAgent` during `meta_report` hero insight generation.
6. `OrchestratorAgent` is keyword/rule based, not LLM function calling.
7. `CriticAgent` is rule based, not an LLM critic.
8. `RetrieverTool` and `FormatterTool` are deterministic tools and do not call LLMs.
9. `/api/v1/query/experimental` now returns 200 for all four service types.
10. `meta_report` uses the v2.1 experimental path; `patch_impact`, `team_report`, and `claim_verification` fall back to stable legacy services.
11. Natural-language role parsing is not implemented. `Strongest midlane heroes` still becomes `role="offlane"`.
12. The frontend `AskConsole` calls the v2.1 experimental endpoint directly at `http://127.0.0.1:8000/api/v1/query/experimental` to avoid Next dev proxy issues.

## Current Status

| Module | Current Status | Ground Truth |
|--------|----------------|--------------|
| Legacy Meta Report | ✅ Working | OpenDota `/heroStats` + local patch JSON; formula/rule based, no LLM |
| v2.1 Experimental Meta Report | ✅ Working | Retriever + Analyzer + Critic + Formatter; Analyzer calls LLM once per top-10 hero for `reasons` and `practice_advice` |
| Patch Impact | ✅ Working | Stable legacy service over `7_41d.json` with 189 changes; experimental endpoint falls back to it |
| Team Report | ✅ Working | Stable legacy service; uses OpenDota when available and mock fallback otherwise; experimental endpoint falls back to it |
| Claim Verification | ⚠️ Mock/rule based | Stable legacy service with hardcoded rules; experimental endpoint falls back to it and runs rule Critic |
| Orchestrator | ⚠️ Rule based | Keyword service routing only; no role parsing; no LLM function calling |
| Analyzer | ✅ Partial LLM | Only meta_report hero insights use LLM; scoring/evidence remain rules |
| Critic | ⚠️ Rule based | Layer 1 rule review only; Layer 2 LLM critic not implemented |
| RetrieverTool | ✅ Meta path working | `retrieve_meta()` uses OpenDota + patch JSON; other retrieve methods exist but the experimental fallback path does not use them yet |
| FormatterTool | ✅ Meta path working | Currently formats `MetaReportResponse` |
| Frontend Dashboard | ✅ Working | `AskConsole` can call the experimental endpoint; SSR panels still call legacy APIs with mock fallback |
| CAP Payment Integration | ❌ Not implemented | Static service catalog shape only |

## Main Entrypoints

### Start Backend

```bash
npm run dev:api
```

Actual command:

```bash
cd apps/api && python -m uvicorn app.main:app --reload --port 8000
```

### Start Frontend

```bash
npm run dev:web
```

Frontend URL:

```text
http://localhost:3012
```

### v2.1 Experimental Endpoint

```bash
curl -X POST http://127.0.0.1:8000/api/v1/query/experimental \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"Strongest offlane heroes\",\"game\":\"dota2\"}"
```

### Stable Legacy Endpoints

```text
POST /api/v1/meta-report
POST /api/v1/patch-impact
POST /api/v1/team-report
POST /api/v1/verify-claim
GET  /api/v1/services
```

## Current v2.1 Experimental Flow

### meta_report Query

```text
POST /api/v1/query/experimental
  -> ExperimentalService.handle_query()
  -> OrchestratorAgent.plan()
       currently chooses only service type; meta role is hardcoded to offlane
  -> RetrieverTool.retrieve_meta(role="offlane", patch="latest")
       OpenDota hero stats + local patch JSON
  -> AnalyzerAgent.analyze_meta_report()
       rule formula computes meta_score/confidence/evidence
       if llm_enabled=True, calls LLM once per hero for reasons/practice_advice
  -> CriticAgent.review_evidence()
       Layer 1 rule review
  -> FormatterTool.format_meta_report()
  -> NaturalLanguageQueryResponse
```

### patch/team/claim Queries

```text
POST /api/v1/query/experimental
  -> ExperimentalService.handle_query()
  -> OrchestratorAgent.plan()
  -> fallback to stable legacy service
       patch_impact        -> PatchImpactService
       team_report         -> TeamReportService
       claim_verification  -> ClaimVerificationService + CriticAgent.review_evidence()
  -> NaturalLanguageQueryResponse
```

## Current LLM Scope

### Implemented

LLM provider:

```text
apps/api/app/llm/provider.py
```

Analyzer caller:

```text
apps/api/app/agents/analyzer.py
```

Call chain:

```text
ExperimentalService._handle_meta_report()
  -> AnalyzerAgent.analyze_meta_report()
  -> AnalyzerAgent._generate_hero_insights()
  -> self.llm.complete_json(...)
  -> OpenAICompatibleProvider.complete_json()
  -> DeepSeek/OpenAI-compatible API
```

LLM-generated fields:

```text
HeroRecommendation.reasons
HeroRecommendation.practice_advice
```

### Not Implemented

```text
Orchestrator LLM function calling
Analyzer unified LLM task_type handling for patch/team/claim
Critic Layer 2 LLM review
LLM retry / budget / cache / batching
```

## LLM Logging

Key LLM and agent flow logs are now emitted at `INFO/WARNING/ERROR` level.

Covered points:

```text
Experimental query start/complete
Orchestrator planned service
Retriever start/complete
Analyzer start/complete
Per-hero score/evidence
Per-hero LLM insight request start/success/failure
LLM provider complete_json start/success/failure
Critic review result
Formatter complete
Fallback service start/complete
```

Logs do not print:

```text
API keys
full prompts
full LLM responses
full user query text
```

Note: `httpx` may also log request status, for example:

```text
INFO:httpx:HTTP Request: POST https://api.deepseek.com/chat/completions "HTTP/1.1 200 OK"
```

## Frontend State

Key files:

```text
apps/web/src/components/AskConsole.tsx
apps/web/src/lib/api.ts
apps/web/src/types/report.ts
```

`AskConsole` behavior:

```text
User enters query
  -> runExperimentalQuery(query)
  -> fetch http://127.0.0.1:8000/api/v1/query/experimental
  -> render routed_service, trace, top 3 hero sample or summary
```

Why `127.0.0.1` is used:

1. Next route handler and rewrites proxy were tried earlier.
2. Browser requests showed `Remote Address: [::1]:3012` and Next returned 500.
3. The backend had no logs, which meant requests stopped inside the Next dev server.
4. The final working approach is direct browser-to-FastAPI IPv4 requests.

Current allowed CORS origins:

```text
http://localhost:3000
http://localhost:3012
http://localhost:3013
```

## Completed Work

### Data Sources And Stable Services

1. OpenDota REST API is wired.
2. Local patch JSON exists at `apps/api/app/data/patches/7_41d.json`.
3. Hero role mapping has an override table.
4. Stable `meta_report`, `patch_impact`, `team_report`, and `claim_verification` services work.
5. The frontend dashboard runs and has mock fallback.

### v2.1 Skeleton And Experimental Path

1. Added `agents/orchestrator.py`, `agents/analyzer.py`, `agents/critic.py`.
2. Added `tools/retriever.py`, `tools/formatter.py`.
3. Added `config/signals.yaml`, `config/critic_rules.yaml`.
4. Added `services/experimental_service.py`.
5. Added `/api/v1/query/experimental`.
6. The experimental endpoint returns results for all four service types.
7. `patch/team/claim` fallback to stable services until native v2.1 implementations are built.

### LLM Enhancement

1. Added an LLM provider abstraction for DeepSeek/OpenAI-compatible APIs.
2. `AnalyzerAgent` can call LLM to generate hero recommendation reasons and practice advice.
3. LLM failures do not block base reports; they return empty `reasons/practice_advice`.
4. Key flow logging has been added.

## Current Test Status

Last backend verification:

```bash
cd apps/api
python -m pytest
```

Result:

```text
17 passed
```

Frontend typecheck:

```bash
npm run typecheck
```

Result:

```text
tsc --noEmit passed
```

Ruff on touched files:

```bash
cd apps/api
python -m ruff check app\main.py app\llm\provider.py app\agents\analyzer.py app\services\experimental_service.py app\tools\formatter.py
```

Result:

```text
All checks passed
```

Note: full `python -m ruff check .` may still report pre-existing lint issues in older files. Do not assume they were introduced by the latest changes.

## Known Limitations And Pitfalls

1. Orchestrator does not parse roles.

   `Strongest midlane heroes`, `carry recommendations`, and `support heroes` may still produce `MetaReportRequest(role="offlane")`.

   File: `apps/api/app/agents/orchestrator.py`

2. LLM calls are sequential per hero.

   A top-10 meta report performs 10 LLM requests and currently takes about 20-30 seconds.

3. LLM API key configuration needs hardening.

   Future Agents should ensure real keys come only from `.env` or secure secret injection. Do not log or commit keys.

4. Critic is not an LLM critic.

   It only checks empty evidence and unsupported signals.

5. Claim Verification remains rule/mock based.

   It does not yet aggregate patch JSON + OpenDota evidence.

6. Patch impact scoring is simple buff/nerf counting.

   It does not weight change magnitude.

7. Team report hero pool depth uses historical data, not a recent-time window.

8. Frontend SSR panels require the backend to be running or they fall back to mocks.

9. `README.md` and some milestone docs may be stale.

   For handoff, prefer this file and current code.

## Recommended Next Steps

### High Priority

1. Add role parsing to `OrchestratorAgent`.

   Support `midlane/mid/position 2`, `carry/pos 1`, `offlane/pos 3`, `support/pos 4/pos 5`.

2. Remove any LLM API key default from code.

   Only `.env` or secure secret injection should provide credentials.

3. Reduce LLM latency.

   Options: call LLM only for top 3 heroes, parallelize calls, cache outputs, or add a request/frontend `llm_enabled` switch.

4. Add role parsing tests for the experimental endpoint.

5. Update API docs to describe `/api/v1/query/experimental` fallback behavior.

### Medium Priority

1. Implement Critic Layer 2 LLM review.
2. Implement real evidence aggregation for Claim Verification.
3. Migrate patch/team/claim from fallback to native v2.1 paths.
4. Add LLM function calling or a stronger deterministic parser to Orchestrator.
5. Add LLM budget, timeout, retry, and cache controls.

### Low Priority

1. CAP integration.
2. Database persistence for report history.
3. STRATZ GraphQL for detailed draft data.
4. Demo video.

## Current Directory Map

```text
apps/api/app/
├── agents/
│   ├── orchestrator.py       # v2.1 rule Orchestrator, currently no role parsing
│   ├── analyzer.py           # v2.1 Analyzer, calls LLM in meta_report
│   ├── critic.py             # v2.1 rule Critic
│   ├── data_agent.py         # legacy stable path still uses this
│   ├── patch_agent.py        # legacy stable path still uses this
│   ├── reasoning_agent.py    # legacy stable path still uses this
│   ├── verification_agent.py # legacy stable path still uses this
│   └── report_agent.py       # legacy stable path still uses this
├── llm/
│   └── provider.py           # DeepSeek/OpenAI-compatible provider
├── tools/
│   ├── retriever.py          # v2.1 deterministic retriever
│   └── formatter.py          # v2.1 deterministic formatter
├── services/
│   ├── experimental_service.py       # v2.1 experimental orchestration service
│   ├── meta_report_service.py        # legacy stable meta report
│   ├── patch_impact_service.py       # legacy stable patch impact
│   ├── team_report_service.py        # legacy stable team report
│   └── claim_verification_service.py # legacy stable claim verification
└── api/v1/routes.py          # HTTP routes, including /query/experimental
```

```text
apps/web/src/
├── components/AskConsole.tsx # v2.1 experimental UI entrypoint
├── lib/api.ts                # runExperimentalQuery directly calls 127.0.0.1:8000
└── types/report.ts           # NaturalLanguageQueryResponse and related types
```

## Documentation Structure

```text
docs/
├── design/
│   ├── MetaMind_MVP_v1.md
│   ├── MetaMind_MVP_v2.md
│   └── MetaMind_MVP_v2.1.md
├── technical/
│   ├── api.md
│   ├── architecture.md
│   └── cap-integration.md
└── progress/
    ├── progress_zh.md
    └── progress_en.md
```
