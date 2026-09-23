# API

This directory contains the FastAPI application and the vNext model-facing
tool layer. The current default surface includes Artifact management,
`esports.league.search`, `esports.series.search`,
`esports.tournament.search`, and `esports.match.search`; the target is defined
in the repository's core documentation.

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

## Current surface

The currently running service exposes `GET /health`, the stateless
`/api/v1/plan` debug endpoints, Chat Session and Chat Run endpoints under
`/api/v1/chat`, and `GET /debug/plan`. This list is operational context only;
it does not define future domain capability contracts.

The default Agent tool registry currently includes Artifact tools and the
closed `esports.league.search`, `esports.series.search`,
`esports.tournament.search`, and `esports.match.search` capabilities. No domain
tool is retained through a compatibility alias.

Runtime configuration and implementation details remain in the code until the
corresponding vNext capability replaces them. Do not add new vNext architecture
to this README; update the relevant document under `docs/` instead.

### Context governance configuration

The normal vNext chat entry point enables automatic context management and
single overflow recovery when `DOTAMIND_CONTEXT_WINDOW_TOKENS` is set to the
verified context window of the configured model. Leave it empty to keep this
feature disabled. The remaining context and compaction limits can be set with
the `DOTAMIND_CONTEXT_*` and `DOTAMIND_COMPACTION_*` variables shown in the root
`.env.example`.

Local API starts, scripts, and evaluations read the repository-root .env.
VNextSettings.from_env() uses process environment values first, then root .env,
then code defaults. The root .env.example is a template only. Docker Compose
injects the same root file into the API container; the real .env is excluded
from the build context and image. Compose's explicit database and Redis
environment values retain their container-network addresses. Recreate the API
container after changing .env:
`docker compose -f compose.wsl.yml up -d --no-deps --force-recreate api`.

The model window must be established from the actual configured model; this
project does not infer or provide a model-to-window mapping. A configured window
enables automatic management for subsequently constructed runtimes, while an
empty window disables it. The output reserve also becomes the output-token limit
for business model calls when capacity management is enabled. The bytes-per-token
setting is an estimate, and the compaction input byte limit is not a model token
window.

## Test

```bash
uv run pytest
```
