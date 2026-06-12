# Architecture

MetaMind is organized around three product surfaces:

```text
Web Dashboard
+ Callable Agent Service
+ CAP Paid Service
```

## Backend

The FastAPI backend exposes report services under `/api/v1`.

```text
app/
  api/v1/          HTTP schemas and routes
  agents/          planner, data, patch, reasoning, verification, report agents
  data/            fixtures used by the mock-first MVP
  integrations/    OpenDota, STRATZ, and patch-note clients
  services/        callable service contracts
```

The service layer is intentionally separate from routes so future adapters can call the same code from:

- HTTP endpoints
- A2A agent handlers
- CAP order callbacks
- scheduled report generation jobs

## Workflow

```text
1. Planner Agent
   Understands the user request and chooses meta, patch, team, or verification flow.

2. Data Agent
   Reads normalized hero, match, draft, and source signals.

3. Patch Agent
   Extracts hero, item, and mechanic changes from official patch notes.

4. Meta Reasoning Agent
   Applies MVP formulas such as Meta Score and Patch Adaptation Score.

5. Verification Agent
   Labels evidence as supported, partially supported, weakly supported, or unsupported.

6. Report Agent
   Produces human-readable summaries and structured JSON.
```

## Scoring

Initial Meta Score:

```text
0.30 * win_rate_score
+ 0.25 * pick_rate_score
+ 0.20 * pro_presence_score
+ 0.15 * patch_impact_score
+ 0.10 * trend_score
```

Initial Patch Adaptation Score:

```text
0.30 * recent_win_rate
+ 0.25 * meta_hero_usage
+ 0.20 * draft_flexibility
+ 0.15 * hero_pool_depth
+ 0.10 * opponent_strength
```

The mock MVP only implements hero meta scoring. Team adaptation is represented by fixture output until pro match ingestion is connected.

## Frontend

The Next.js app is an app-style dashboard, not a marketing page.

Main modules:

- Query console
- KPI cards
- Meta report ranking table
- ECharts score chart
- Patch impact panel
- Team intelligence panel
- Agent API / CAP service catalog

The dashboard uses backend responses when `NEXT_PUBLIC_API_BASE_URL` is reachable and falls back to local mock data while the backend is offline.
