# MetaMind API

FastAPI backend for the MetaMind MVP.

## Run

```bash
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --port 8000
```

## Endpoints

- `GET /health`
- `GET /api/v1/services`
- `POST /api/v1/meta-report`
- `POST /api/v1/patch-impact`
- `POST /api/v1/team-report`
- `POST /api/v1/verify-claim`
- `POST /api/v1/query`

## Configuration

Secrets, environment-specific URLs, and feature flags are loaded from `.env`. Business policy
is loaded from `app/config/policy.yaml` and validated by Pydantic at startup.

```text
METAMIND_OPENDOTA_API_KEY=...
METAMIND_LLM_API_KEY=...
METAMIND_LIVE_DATA_ENABLED=true
METAMIND_POLICY_PATH=optional/absolute/path/to/policy.yaml
```

`policy.yaml` is the single source for OpenDota transport settings, team resolution and sampling,
hero scoring and evidence thresholds, patch scoring, Critic rules, and LLM call parameters.
Patch facts remain under `app/data/patches/`, and prompt text remains under
`app/resources/prompts/`.
