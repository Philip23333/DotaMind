# MetaMind Implementation Progress

> Last updated: 2026-06-12

## Project Overview

MetaMind is a composable esports intelligence agent that turns Dota2 patch notes, match data, and pro team statistics into verifiable, paid meta analysis reports for humans and other agents.

---

## Current Status

| Module | Status | Data Source |
|--------|--------|-------------|
| Meta Report (hero recommendations) | ✅ Live | OpenDota /heroStats + patch JSON |
| Patch Impact (version analysis) | ✅ Live | Local patch JSON (189 changes) |
| Team Report (team analysis) | ✅ Live | OpenDota /teams + /matches + /heroes |
| Claim Verification | ⚠️ Mock | Hardcoded rules |
| Service Catalog | ✅ Static | No external data needed |
| CAP Payment Integration | ❌ Not implemented | — |
| Frontend Dashboard | ✅ Functional | Depends on backend running |

---

## Completed Work

### Phase 1: Data Source Integration

1. **OpenDota REST API**
   - `/heroStats`: win rate, pick rate, ban rate, pro match data
   - `/teams`: team search (fuzzy match on name and tag)
   - `/teams/{id}/matches`: recent N match records
   - `/teams/{id}/heroes`: team hero pool statistics
   - In-memory cache with 1h TTL

2. **Patch Notes Structuring**
   - Hand-curated 7.41d patch notes → `data/patches/7_41d.json`
   - 189 changes (116 buffs / 71 nerfs / 2 neutral)
   - Covers heroes, items, neutral items, enchantments

3. **Hero Role Mapping**
   - OpenDota role tags → canonical positions (carry/mid/offlane/support)
   - 40+ hero override table for classification corrections (e.g., Mars/Tidehunter → offlane)

### Phase 2: Service Logic

4. **Meta Report Service** (async)
   - High-MMR win rate (Ancient+) as primary ranking signal
   - Patch JSON injects `patch_impact_score` (buff +0.15, nerf -0.15 per change)
   - Weighted formula: win rate 30% + pick rate 25% + pro presence 20% + patch impact 15% + trend 10%
   - Returns top 10 heroes; degrades to mock on OpenDota failure

5. **Patch Impact Service**
   - Counts buff/nerf per hero from JSON → winners and losers
   - Auto-generates summary, item impacts, lineup trends
   - Confidence dynamically computed from data completeness (0.6–0.9)

6. **Team Report Service** (async)
   - Supports any team query (fuzzy match by name/tag)
   - Recent 30-match win/loss record
   - Top 5 signature heroes (by historical games_played)
   - Hero pool depth (heroes with ≥30 games)
   - Draft flexibility, patch adaptation score
   - Average win/loss game duration analysis
   - Degrades to mock on failure

### Phase 3: Engineering Foundation

7. **Testing**
   - 4 service tests passing (pytest + pytest-asyncio)
   - meta_report / patch_impact / team_report / claim_verification

8. **Environment**
   - `.env` with CORS config (ports 3000/3012/3013)
   - docker-compose with Postgres + Redis (not wired to code)
   - pydantic-settings configuration management

---

## Remaining Work

### High Priority

| Task | Description | Estimated Time |
|------|-------------|----------------|
| 3-Agent refactor | Collapse 6 agents → Retriever/Analyzer/Formatter | 3-4h |
| signals.yaml | Boolean signal extraction per v2 design (thresholds in config) | 2-3h |
| Claim Verification | Wire to patch JSON + OpenDota for evidence aggregation | 2h |
| Backtest script | `eval/backtest.py`, top-10 overlap across 3 historical patches | 2h |

### Medium Priority

| Task | Description | Estimated Time |
|------|-------------|----------------|
| LLM integration (Analyzer) | GPT-4 for reasoning + verification, generate reasons/practice_advice | 3h |
| CAP integration | Expose paid services, wire to CROO Agent Store | 4-6h |
| STRATZ GraphQL | Time-filtered team draft data in single query | 4h |

### Low Priority

| Task | Description | Estimated Time |
|------|-------------|----------------|
| Dynamic frontend queries | AskConsole routes to backend | 2h |
| Multi-role support | Frontend role selector (carry/mid/support) | 1h |
| Database persistence | Report archival + history queries | 3h |
| Demo video | 5-minute recording | 2h |

---

## Architecture

```
apps/api/
├── app/
│   ├── agents/          # data_agent / patch_agent / reasoning / verification / report / planner
│   ├── api/v1/          # routes + schemas (Pydantic models)
│   ├── core/            # config (pydantic-settings)
│   ├── data/
│   │   ├── mock_data.py # Static fallback data
│   │   └── patches/     # Structured patch JSON
│   │       └── 7_41d.json
│   ├── integrations/
│   │   ├── opendota.py  # REST client + in-memory cache + role mapping
│   │   ├── patch_notes.py  # Local JSON reader + patch score computation
│   │   └── stratz.py    # Placeholder
│   └── services/        # meta_report / patch_impact / team_report / claim_verification / pricing
└── tests/
```

```
apps/web/                # Next.js 15 + Tailwind + ECharts
├── src/
│   ├── app/page.tsx     # SSR home page, fetches 4 backend APIs
│   ├── components/      # 5 panel components + AppShell + AskConsole
│   ├── lib/api.ts       # Fetch wrapper with mock fallback
│   └── types/report.ts  # TypeScript type definitions
```

---

## Data Flow

```
User request
  → FastAPI route (async)
    → DataAgent.hero_stats_for_role_async()
      → OpenDotaClient.get_hero_stats_for_role()
        → GET https://api.opendota.com/api/heroStats (1h cache)
      → _inject_patch_scores()
        → patch_notes.compute_hero_patch_score("latest")
          → Read data/patches/7_41d.json
    → ReasoningAgent.meta_score() (weighted formula)
    → VerificationAgent.hero_evidence() (rule-based)
  → Return MetaReportResponse JSON
```

---

## Known Limitations

1. **Hero pool depth** uses all-time historical data (≥30 games), not recent matches; requires STRATZ or paid OpenDota key to fix
2. **patch_impact_score** uses simple buff/nerf counting, doesn't weight change magnitude
3. **Role mapping** relies on override table; new heroes must be added manually
4. **Frontend SSR** requires backend to be running first, otherwise falls back to mock
5. **No LLM reasoning** — reasons/practice_advice fields are empty; meta_score is pure formula

---

## Documentation Structure

```
docs/
├── design/              # Product design docs
│   ├── MetaMind_MVP_v1.md    # Original MVP design (full version)
│   └── MetaMind_MVP_v2.md    # Engineering revision (architecture + algorithm + data source)
├── technical/           # Technical docs
│   ├── api.md                # API reference
│   ├── architecture.md       # System architecture
│   └── cap-integration.md    # CAP integration plan
└── progress/            # Implementation progress
    ├── progress_zh.md        # 中文版
    └── progress_en.md        # This file
```
