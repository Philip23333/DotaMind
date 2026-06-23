# MetaMind API

FastAPI backend for the MetaMind MVP.

## Run

```bash
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001 --log-level info
```

From the repository root, `npm run dev:api` runs `dev-api.cmd`, which uses fixed port `8001` and exits with an error when the port is already occupied.

## Query Smoke Runner

With the API running on `127.0.0.1:8001`, run:

```bash
python scripts/query_smoke.py
```

The runner calls `/api/v1/query` with representative natural-language prompts and prints the
HTTP status, route, Critic quality-gate status, key report fields, sources, and elapsed time.
Use `--base-url` to target a different local API instance.

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
METAMIND_LIVE_DATA_ENABLED=true
METAMIND_LLM_ENABLED=true
METAMIND_LLM_API_KEY=...
METAMIND_LLM_BASE_URL=https://api.deepseek.com
METAMIND_LLM_MODEL=deepseek-chat
METAMIND_POLICY_PATH=C:/optional/absolute/path/to/policy.yaml
```

`policy.yaml` is the single source for OpenDota transport settings, team resolution and sampling,
hero scoring and evidence thresholds, patch scoring, Critic rules, and LLM call parameters.
Patch facts remain under `app/data/patches/`, and prompt text remains under
`app/resources/prompts/`.

Policy is cached for the process lifetime. Restart the API after changing `policy.yaml` or an override file pointed to by `METAMIND_POLICY_PATH`.
