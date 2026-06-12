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
