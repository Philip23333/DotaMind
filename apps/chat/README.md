# DotaMind Chat

This Next.js and assistant-ui client is the current chat interface. It does not
run a model locally. Its present API integration and runtime behavior belong to
Legacy V3 and may be replaced as the vNext backend is delivered; the target
architecture is defined in [docs/](../../docs/README.md).

## Local development

Start the API on `http://localhost:8001`, then run:

```bash
cd apps/chat
npm install
npm run dev
```

Open `http://localhost:3000`.

To use a different API address, copy `.env.local.example` to `.env.local` and
set:

```text
NEXT_PUBLIC_DOTAMIND_API_URL=http://localhost:8001
```

`NEXT_PUBLIC_DOTAMIND_TEST_OBSERVER_ENABLED` is a Legacy local-debug setting.
Do not enable it outside a local test environment.

## UI direction

The client presents streaming chat, sources, freshness, and uncertainty in a
readable form. Structured match views may be used where they communicate facts
more reliably than generated prose. The client must not invent provider URLs or
turn model text into unverified data.

## Test

```bash
npm run test
npm run lint
npm run build
```
