# API

Base URL:

```text
http://localhost:8001
```

## Health

```http
GET /health
```

## Service Catalog

```http
GET /api/v1/services
```

Returns callable service names, endpoints, prices, and input shapes.

## Meta Report

```http
POST /api/v1/meta-report
```

Request:

```json
{
  "game": "dota2",
  "patch": "latest",
  "role": "offlane"
}
```

Response highlights:

- `top_heroes`
- `meta_score`
- `confidence`
- `evidence`
- `sources`
- `analysis_steps`

## Patch Impact

```http
POST /api/v1/patch-impact
```

Request:

```json
{
  "game": "dota2",
  "patch": "latest",
  "role": "offlane"
}
```

Response highlights:

- `winners`
- `losers`
- `item_impacts`
- `lineup_trends`
- `practice_advice`

## Team Report

```http
POST /api/v1/team-report
```

Request:

```json
{
  "game": "dota2",
  "team_name": "Team Spirit",
  "time_range": "last_30_days"
}
```

Response highlights:

- `recent_record`
- `matches_in_window`
- `match_details_analyzed`
- `data_freshness.latest_match_at`
- `data_freshness.sample_window_days`
- `data_freshness.opendota_cache_hits`
- `data_freshness.opendota_cache_misses`
- `signature_heroes`
- `draft_preferences`
- `win_patterns`
- `loss_patterns`
- `patch_adaptation_score`

`data_freshness` is emitted for team reports so callers can judge whether the
OpenDota evidence is recent enough for the requested decision. The root-level
`matches_in_window` and `match_details_analyzed` fields are kept for backward
compatibility and mirrored inside `data_freshness`.

Ambiguous natural-language team queries return `409 ambiguous_team` with candidate teams and the original `time_range`. `/api/v1/query` accepts `team_selection` to submit a selected `team_id` without another LLM planning call.

## Claim Verification

```http
POST /api/v1/verify-claim
```

Request:

```json
{
  "game": "dota2",
  "claim": "Beastmaster is one of the strongest offlaners in current patch."
}
```

Response highlights:

- `verdict`
- `evidence`
- `confidence`
- `missing_data`

## Natural Language Query

```http
POST /api/v1/query
```

Request:

```json
{
  "game": "dota2",
  "query": "I play position 3. Which heroes should I practice?"
}
```

The Orchestrator routes to one report task and the canonical pipeline returns executed steps plus the selected result. There is no separate experimental query endpoint.

Optional team selection after an ambiguous response:

```json
{
  "game": "dota2",
  "query": "How Team BB play lately?",
  "team_selection": {
    "team_id": 8255888,
    "team_name": "BB",
    "time_range": "last_30_days"
  }
}
```
