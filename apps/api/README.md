# Legacy API

This directory contains the Legacy V3 FastAPI backend. It remains runnable
during the vNext rewrite, but it is not the architecture authority and will be
replaced incrementally. The vNext target is defined in the repository's
[core documentation](../../docs/README.md).

## Run locally

Python 3.10+ is required. The recommended workflow uses
[`uv`](https://docs.astral.sh/uv/).

From the repository root:

```bash
uv sync --project apps/api --extra dev
uv run --project apps/api uvicorn app.main:app --app-dir apps/api --reload --host 127.0.0.1 --port 8001 --log-level info
```

Or from this directory:

```bash
uv sync --extra dev
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8001 --log-level info
```

If `uv` is unavailable, install and run from the same Python interpreter:

```bash
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001 --log-level info
```

Useful local pages:

- `http://localhost:8001/docs`
- `http://localhost:8001/debug/plan`

## Current Legacy surface

The currently running service exposes `GET /health`, the stateless
`/api/v1/plan` debug endpoints, Chat Session and Chat Run endpoints under
`/api/v1/chat`, and `GET /debug/plan`. This list is operational context only;
it does not define new vNext contracts.

Runtime configuration and implementation details remain in the code until the
corresponding vNext capability replaces them. Do not add new vNext architecture
to this README; update the relevant document under `docs/` instead.

## Test

```bash
uv run pytest
```
