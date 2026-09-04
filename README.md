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
model-facing capability layer is intentionally at an artifact-only baseline;
domain capabilities will be rebuilt behind explicit contracts.

## Tool surface

The vNext tool layer is currently being rebuilt. The active default registry
exposes only Artifact-management tools. Domain tools will be added
incrementally behind explicit domain contracts.

## Local development

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
