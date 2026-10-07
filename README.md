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
CLI through WSL interop. It always loads both `compose.wsl.yml` and
`compose.data.yml`: the API reads the shared data volume read-only, and the
updater writes to that same volume. With WSL Integration enabled, the equivalent
command is `docker compose -f compose.wsl.yml -f compose.data.yml up -d --build --wait`.

### Tool-result Artifact budgets

The API reads two UTF-8 serialized-byte limits from the root `.env` or process
environment; process environment values take precedence. The defaults preserve
current behavior: `DOTAMIND_TOOL_INLINE_MAX_BYTES=12288` keeps results up to
12 KiB inline, while larger results are stored as complete Artifacts, and
`DOTAMIND_TOOL_OBSERVATION_MAX_BYTES=35840` bounds the preview and successful
`artifact.read` results to 35 KiB. Both values must be positive integers and the
inline limit cannot exceed the observation limit. Restart the API after changing
either value.

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
container with `docker compose -f compose.wsl.yml -f compose.data.yml up -d --no-deps --force-recreate api`.

### Agent time budgets

The vNext Agent reads `DOTAMIND_EXECUTION_DEADLINE_SECONDS` (default `300`)
and `DOTAMIND_ANSWER_DEADLINE_SECONDS` (default `60`) from the repository-root
`.env`. Process environment variables override `.env`, which overrides code
defaults. Both settings accept finite positive seconds, including decimals.
Execution and answer are timed independently. The answer budget includes answer
context preparation, compaction and recovery, the primary answer, and any
degraded answer; a degraded attempt uses only the time left in that same
budget. If it is exhausted, Runtime uses its existing no-model fallback.

Execution has no step-count ceiling. Runtime still numbers and traces each step;
the execution deadline, cancellation, completed plans, and existing capacity or
error exits govern when the stage ends. Changes to `.env` take effect after the
API is restarted or its container is recreated.

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

Summary requests have no separate fixed input byte ceiling. Runtime measures each
fully constructed summary request, including its instruction, prior summary when
present, and source history, using the same canonical UTF-8 byte-ratio estimate
as ordinary requests. A summary call is sent only when its estimated input tokens,
its reserve-derived summary output allowance, and the configured safety margin
fit within the model context window. Without a configured window, explicit
compaction remains available and the trace marks its capacity as unvalidated.

Ordinary execution and answer calls require at least one of
`DOTAMIND_MODEL_MAX_OUTPUT_TOKENS` or
`DOTAMIND_APPLICATION_MAX_OUTPUT_TOKENS`. The model cap records the known
per-response limit for the configured model/provider; the application cap is an
optional operator ceiling. If both are set, the lower value is the expected
output cap. With `DOTAMIND_CONTEXT_WINDOW_TOKENS` configured, Runtime measures
the complete request input and clips that expected cap to the space remaining
after `DOTAMIND_CONTEXT_SAFETY_MARGIN_TOKENS`. Without a context window, calls
still use the finite expected cap, while automatic capacity governance remains
disabled. These values must be configured from verified model/provider limits;
the repository does not assert a universal default. The former
`DOTAMIND_CONTEXT_OUTPUT_RESERVE_TOKENS` setting is no longer read and is not
mapped to either cap.

Dynamic output budgeting is implemented. JSON correction, whole-batch refusal,
and bounded generation recovery remain pending; live Provider compatibility
validation is also pending. See the authoritative
[model output and recovery contract](docs/agent/model_output_and_recovery.md).

Automatic compaction uses the production threshold when the test override is
blank:

```dotenv
DOTAMIND_COMPACTION_RESERVE_TOKENS=16384
DOTAMIND_CONTEXT_COMPACTION_TEST_TRIGGER_PERCENT=
```

The production condition is `estimated_input_tokens > context_window_tokens -
compaction_reserve_tokens`. Reserve must be smaller than the configured model
window. The reserve also derives summary output limits, so it should not be
changed merely to simulate early triggering.

For deterministic pressure tests, a separate test-only percentage may advance
the trigger without changing summary budgets or history slicing:

```dotenv
DOTAMIND_COMPACTION_RESERVE_TOKENS=16384
DOTAMIND_CONTEXT_COMPACTION_TEST_TRIGGER_PERCENT=30
```

The test percentage is rounded up from the input budget after the current
request's output reserve and safety margin are removed. The effective trigger
is the earlier of the production threshold and this test threshold; it can
never delay production triggering. `CRITICAL` hard-capacity handling takes
priority. Leave `DOTAMIND_CONTEXT_WINDOW_TOKENS` blank to disable automatic
capacity governance. The old `DOTAMIND_CONTEXT_COMPACTION_TRIGGER_PERCENT`
variable is no longer read and must be removed/migrated.

After changing API settings, restart the backend; for container deployments,
also verify that the running container uses the intended image. These settings
do not infer a model's actual window. Input sizing remains a configurable UTF-8
byte-ratio heuristic, not an exact tokenizer or provider usage measurement.

`DOTAMIND_COMPACTION_MAX_RETRIES` defaults to `1` and means retries after the
first call (allowed range: 0–3), independently for each summary segment. Only
classified temporary provider/network failures retry, with fixed 1/2/4-second
backoff; the original execution or answer deadline covers both waiting and
calls. Truncated (`finish_reason=length`), empty or invalid summaries, quota
exhaustion, and other permanent errors are not retried. Both segments must
succeed before the atomic history update; exhausted or rejected compaction
stops the current task and leaves the previous effective history intact.
Ordinary business model calls are not retried by this setting. Summary retries
are real model calls and count toward request/evaluation call budgets; they do
not consume or replenish the separate one-time provider-overflow recovery.

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
