# API

Base URL:

```text
http://localhost:8000
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
- `signature_heroes`
- `draft_preferences`
- `win_patterns`
- `loss_patterns`
- `patch_adaptation_score`

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
