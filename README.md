# DotaMind

DotaMind is being rebuilt as a Dota 2 esports agent: a conversational product
for professional competitions, matches, teams, players, and the game facts
needed to understand them.

The repository is in a clean-slate vNext rewrite. Legacy V3 is preserved at the
Git tag [`pre-vnext-rewrite`](https://github.com/Philip23333/DotaMind/tree/pre-vnext-rewrite);
it is historical context, not a compatibility contract for new work.

## vNext architecture

- [Product](docs/PRODUCT.md) — what DotaMind is and is not building
- [Architecture](docs/ARCHITECTURE.md) — layer ownership and runtime shape
- [Tools](docs/TOOLS.md) — agent-visible domain capabilities
- [Data](docs/DATA.md) — identity, providers, normalization, and provenance
- [Evals](docs/EVALS.md) — behavioral and live-integration acceptance
- [Roadmap](docs/ROADMAP.md) — implementation order

Read these documents before changing vNext architecture or product behavior.

## Current repository state

`apps/api` and `apps/chat` provide the current development surfaces. The
model-facing capability layer currently exposes Artifact management and closed
esports league-, series-, tournament-, and match-search capabilities; additional
domains will be rebuilt behind explicit contracts.

## Tool surface

The vNext tool layer is currently being rebuilt. The active default registry
exposes Artifact-management tools, `esports.league.search`,
`esports.series.search`, `esports.tournament.search`, and
`esports.match.search`. Domain tools will be added incrementally behind explicit
domain contracts.

## Local development

### Run everything in Docker on WSL

Start Docker Desktop with its Linux engine. Copy `.env.example` to `.env`
(or migrate your existing `.env`) and configure your model/provider credentials.
Enable `DOTAMIND_LLM_ENABLED` and `DOTAMIND_LIVE_DATA_ENABLED` for live use.
No local Python or Node installation is required.

```bash
./scripts/compose-wsl.sh up -d --build --wait
./scripts/compose-wsl.sh ps
```

Open `http://localhost:3000` for chat and `http://localhost:8001/docs` for
the API. Nginx forwards the browser's `/api/` requests to the API, including
streaming responses. Override `DOTAMIND_WEB_PORT` or `DOTAMIND_API_PORT` in
`.env` if these ports are occupied. Ports bind to the laptop's loopback interface.

The script uses the WSL Docker CLI when available, or Docker Desktop's Windows
CLI through WSL interop. With WSL Integration enabled, the equivalent command is
`docker compose -f compose.wsl.yml up -d --build --wait`.

This configuration uses the `dotamind` Compose project and its existing
`dotamind_postgres-data` / `dotamind_redis-data` volumes. The database password
must match the existing volume (`dotamind` by default; override with
`DOTAMIND_POSTGRES_PASSWORD`). The API runs Alembic migrations on startup;
back up an existing database before first use. PostgreSQL and Redis are accessed
inside the Docker network, without publishing their ports.

```bash
./scripts/compose-wsl.sh logs --tail=100 api chat nginx
./scripts/compose-wsl.sh stop
# Rebuild after changing source code:
./scripts/compose-wsl.sh up -d --build --wait
```

Containers run built images; source changes require rebuilding. Use `stop` or
`down` to stop the stack; `down -v` also deletes its database and Redis volumes.
The separate `compose.prod.yml` remains the server deployment configuration.

The repository-root .env is the only real configuration file for local API
starts, scripts/evaluations, and Docker. Configuration precedence is process
environment, root .env, then code defaults; .env.example is a template only.
Compose injects the root file into the API container while retaining its
container-specific database and Redis addresses. The real .env is excluded
from the API build context and image. After changing API settings, recreate the
container with `docker compose -f compose.wsl.yml up -d --no-deps --force-recreate api`.

### Context compaction budgets

`DOTAMIND_COMPACTION_RESERVE_TOKENS` defaults to `16384` and derives the
compaction response limit: history summaries use `floor(reserve × 0.8)` and
single-turn prefix summaries use `floor(reserve × 0.5)`. An optional
`DOTAMIND_COMPACTION_MODEL_MAX_OUTPUT_TOKENS` caps either derived value; leave it
blank when the model's output limit is unknown. The reserve is a configuration
budget, not a claim about model capability. Runtime may use both formulas when
a cut crosses a task turn.

`DOTAMIND_COMPACTION_KEEP_RECENT_TOKENS` defaults to `20000` and controls the
estimated-token target retained as raw recent history. It uses the configured
`DOTAMIND_CONTEXT_ESTIMATE_BYTES_PER_TOKEN` heuristic; complete tool-call groups
are kept intact even when one group crosses the target. When migrating an
existing `.env`, replace `DOTAMIND_COMPACTION_RECENT_HISTORY_BYTES` with this
token setting; the old byte variable is no longer read.

These output-token limits are independent from the existing serialized-input
byte limit (`DOTAMIND_COMPACTION_MAX_INPUT_BYTES`). Summary text no longer has a
separate 8 KiB byte ceiling; the complete rebuilt model request remains subject
to the existing context-capacity checks. Ordinary answer output continues to
use `DOTAMIND_CONTEXT_OUTPUT_RESERVE_TOKENS`. This budget change does not alter
the watermark trigger, including the current 30% test setting, or implement Pi's
production trigger formula. A larger reserve can reduce truncation but does not
guarantee a successful summary.

When migrating an existing `.env`, remove the obsolete
`DOTAMIND_COMPACTION_MAX_OUTPUT_TOKENS` and
`DOTAMIND_COMPACTION_MAX_SUMMARY_BYTES` entries; they are no longer read. An
unset/blank model output cap means unknown, while a blank reserve is invalid.

### Run the processes locally

Start the API:

```bash
cd apps/api
uv sync --extra dev
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8001 --log-level info
```

In another terminal, start the current chat client:

```bash
cd apps/chat
npm install
npm run dev
```

Useful local pages are `http://localhost:8001/docs`,
`http://localhost:8001/debug/plan`, and `http://localhost:3000`.

## Verification

```bash
cd apps/api
uv run pytest

cd ../chat
npm run test
npm run lint
npm run build
```

See [the API README](apps/api/README.md) and [the chat README](apps/chat/README.md)
for local run and test details.

## License

MIT. See [LICENSE](LICENSE).
