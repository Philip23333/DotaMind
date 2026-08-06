# DotaMind Progress Snapshot — 2026-08-06

## 20:52 — Single-node Tencent Cloud container deployment

### Completed

- Added production Dockerfiles and ignore files for FastAPI and Next.js, a same-origin Nginx reverse proxy, and `compose.prod.yml`; only public port 80 is published while PostgreSQL, Redis, API, and Chat remain on the internal Docker network.
- Exported `apps/api/requirements.prod.txt` from `apps/api/uv.lock` for pinned production dependencies; the Tencent Cloud build uses its internal PyPI mirror to avoid abnormally slow GHCR/PyPI public downloads.
- Deployed the current local `v3.3` commit and local `.env` over SSH to `159.75.78.201:/opt/dotamind`; the remote `.env` mode is `600` and temporary transfer copies were removed.
- Nginx forwards `/api`, `/health`, `/docs`, `/openapi.json`, and `/debug` to FastAPI and all other requests to Next.js; the Chat build uses a relative API address.
- Added README guidance for Compose deployment, verification, locked dependency export, and the HTTP/TLS boundary.

### Verified

- `docker compose -f compose.prod.yml config --quiet`: passed.
- API and Chat production images built successfully; the Next.js production build and TypeScript checks passed, with zero npm audit vulnerabilities.
- Alembic upgraded an empty PostgreSQL database through `20260805_03`; PostgreSQL and Redis healthchecks are healthy and all five containers remain running.
- Public `GET /`, `GET /health`, and `HEAD /docs` each return HTTP 200.
- Chat Session create, list, and delete smoke tests passed; `chat_sessions` contained zero rows after cleanup.
- A minimal `/api/v1/plan` request completed real DeepSeek calls: the provider returned HTTP 200 on all three attempts and the Agent Graph closed normally as `clarification_required` without runtime errors.

### Boundaries

- The deployment currently uses `http://159.75.78.201` without a domain or HTTPS; Internet-facing production requires TLS termination.
- The default PostgreSQL password is used only inside the Docker network, and Compose supports overriding it with `DOTAMIND_POSTGRES_PASSWORD`; set a random strong password before storing durable production data.
- The local `v3.3` branch is not pushed to GitHub, so this deployment used direct SSH transfer; no deployment files were committed or pushed in this work.

## 21:08 — Public HTTP frontend startup fix

### Completed

- Fixed the Chat startup crash caused by directly calling `crypto.randomUUID()` in a non-secure public HTTP context; added a UUID v4 utility that uses `crypto.getRandomValues()` and sets the RFC 4122 version and variant bits when the platform API is unavailable.
- Routed Browser ID and Chat Run request ID creation through the utility and added unit coverage for both the native and compatibility paths.
- Rebuilt and deployed the `chat` image, then restarted Nginx to refresh upstream container resolution; the API, database, and existing data were unchanged.

### Verified

- Chat: `npm run test` passed all 6 tests across 3 test files; `npm run lint` and `npm run build` passed.
- Public `GET /` and `GET /health` both return HTTP 200; all five Compose containers remain running, with PostgreSQL and Redis healthy.
- After Edge 150 loaded the new static assets from `http://159.75.78.201/`, two `/api/v1/chat/sessions` requests returned HTTP 200, confirming that the frontend progressed beyond the previous initialization crash.

### Boundaries

- This fix makes the current HTTP URL usable, but browsers will still label the connection as not secure; a domain and trusted HTTPS certificate remain separate deployment work before a formal Internet release.
