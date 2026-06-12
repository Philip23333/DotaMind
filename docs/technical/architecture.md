# Architecture

> Architecture is defined by the design docs at `docs/design/`. The latest is **MetaMind_MVP_v2.1.md** (3 Agents + 2 Tools, with adversarial Critic loop). v2 introduced the 6→3 collapse; v2.1 refined the Agent/Tool boundary and added the Critic Agent.

MetaMind is organized around three product surfaces:

```text
Web Dashboard
+ Callable Agent Service
+ CAP Paid Service
```

## Backend Layout

```text
app/
  api/v1/          HTTP schemas and routes
  agents/          orchestrator, analyzer, critic   (LLM-driven)
  tools/           retriever, formatter             (deterministic, no LLM)
  data/            patch JSON + mock fixtures
  integrations/    OpenDota, STRATZ, patch-note clients
  services/        callable service contracts (4 tasks)
  config/          signals.yaml, critic_rules.yaml
```

The service layer is deliberately decoupled from routes so future adapters can call the same code from:

- HTTP endpoints
- A2A agent handlers
- CAP order callbacks
- Scheduled report-generation jobs

## Component Roles (v2.1)

| Component | Type | LLM | Responsibility |
|---|---|---|---|
| **Orchestrator** | Agent | yes | Intent parsing, tool planning, retry control, fallback |
| **Analyzer** | Agent | yes | Claim generation, evidence binding, verdict labeling |
| **Critic** | Agent | yes (+ rules) | Independent review, reject on missing/weak evidence |
| Retriever | Tool fn | no | OpenDota / patch JSON fetching, EvidenceBundle assembly |
| Formatter | Tool fn | no | Render claims to markdown / JSON / A2A response |

The classification rule: **a component is an Agent only if it requires an LLM decision**. Wrapping deterministic code as an "Agent" is rejected as noise.

## Workflow

```text
External caller
  │
  ▼
Orchestrator Agent       (LLM)  parse intent, choose tools
  │
  ├─► retrieve_*()       (fn)   fetch evidence bundle
  │
  ├─► Analyzer Agent     (LLM)  generate claims with evidence_ids
  │
  ├─► Critic Agent       (LLM + rules)  pass / reject + reasons
  │       │
  │       └─ reject ──► back to Orchestrator
  │                     decide: fetch more / re-analyze / give up
  │
  └─► format_report()    (fn)   render output
```

**Retry budget**: Orchestrator allows max 2 Critic rejections before returning `verdict: insufficient_data` with the accumulated reasons.

## Independent Failure Modes

This is what makes the multi-Agent topology meaningful rather than decorative:

- **Orchestrator** can mis-plan: wrong tool, missing tool, infinite loop
- **Analyzer** can hallucinate: claims without evidence, over-confident verdicts
- **Critic** can mis-judge: pass false claims or reject good ones

Three Agents, three independent failure surfaces, all observable in trace logs. This is the textbook Reflexion / Self-Critique pattern.

## Scoring (v2.1)

The v1 weighted Meta Score formula has been **deprecated**. v2 replaced it with **signal aggregation + LLM judgment** (see `docs/design/MetaMind_MVP_v2.md` §3); v2.1 keeps that approach.

Pipeline:

```text
1. Signal extraction       (deterministic, thresholds in config/signals.yaml)
2. LLM judgment            (Analyzer)
3. Critic review           (rules + LLM)
4. Confidence bucketing    (high / medium / low / none)
```

Confidence is a discrete bucket, not a float. The bucketing rules are publishable so any reviewer can reproduce them.

## Frontend

The Next.js app is an app-style dashboard, not a marketing page.

Main modules:

- Query console (will route to Orchestrator)
- KPI cards
- Meta report ranking table
- ECharts score chart
- Patch impact panel
- Team intelligence panel
- Agent API / CAP service catalog

The dashboard uses backend responses when `NEXT_PUBLIC_API_BASE_URL` is reachable and falls back to local mock data while the backend is offline.

## Migration Status

- v2 migration (3 Agents) — **partially done**: services are async, OpenDota / patch JSON wired, but `agents/` still holds the legacy 6-Agent layout
- v2.1 migration (3 Agents + 2 Tools + Critic) — **planned**, see `docs/progress/progress_*.md`
