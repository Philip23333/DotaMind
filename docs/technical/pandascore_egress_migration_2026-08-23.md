# PandaScore egress diagnosis and VLESS migration — 2026-08-23

## Status

Completed. The production API on `106.52.89.125` now reaches external HTTP(S)
providers through a private sing-box VLESS sidecar and no longer uses WireGuard.
This record is an operational incident and migration handoff, not an Agent
Runtime or tool-contract design document.

## Scope and boundary

The affected path was PandaScore access from the live `dotamind-api-1`
container. The investigation did not change Controller planning, registered
tools, evidence contracts, answer generation, provider request shapes, or the
current sequential `upcoming` / `running` / `past` behavior.

The DotaMind API and VLESS sidecar run on `106.52.89.125`. The VLESS server is
`96.126.130.87`. VLESS client credentials, Reality parameters, private
configuration JSON, and static binaries are server-only assets and must not be
committed or copied into documentation.

## Diagnosis

The PandaScore tool topology was verified against the current implementation:

1. `pandascore.resolve_competition` requests `/dota2/series` with
   `page[size]=100` when no explicit edition year is supplied, then selects the
   competition locally.
2. `pandascore.list_matches` requests `upcoming`, `running`, and `past`
   sequentially. Its normal default is `page[size]=20` for each endpoint.
3. Each top-level tool handler creates and closes its own `PandaScoreTransport`.
   The three fixture requests share their handler-local client, but the Series
   request does not share it with fixture listing.

The production API container had no `HTTP_PROXY`, `HTTPS_PROXY`, or
`ALL_PROXY` environment variable. A WireGuard `wg0` interface was active on
both servers, but the normal host route inspected on `106.52.89.125` used
`eth0`; an active WireGuard handshake was therefore not evidence that the API
container used that tunnel for PandaScore.

### Measured direct path

These measurements were made inside the live API container using the current
`PandaScoreTransport` and the production token. Live provider data is volatile;
the numbers are latency observations, not permanent performance assertions.

| Request or tool path | Observed duration |
| --- | ---: |
| Series, `page[size]=100` | 20.267 s |
| `list_matches` total | 14.621 s |
| `list_matches`: upcoming | 2.806 s |
| `list_matches`: running | 0.370 s |
| `list_matches`: past | 11.444 s |

The direct request shape therefore reproduced the 35-second user-visible Run
slowdown. The main cause was provider egress latency, especially Series and
past-fixture retrieval, rather than the browser, planner, or local data
processing.

## VLESS implementation

`compose.prod.yml` defines `vless-proxy`, a private sing-box service on the
existing Compose network. It provides an HTTP proxy at
`http://vless-proxy:7890`; the port is not published by Docker.

The API service sets:

```text
HTTP_PROXY=http://vless-proxy:7890
HTTPS_PROXY=http://vless-proxy:7890
NO_PROXY=localhost,127.0.0.1,::1,postgres,redis,vless-proxy
```

`httpx` honors these standard proxy variables, so the existing PandaScore,
OpenDota, STRATZ, and compatible LLM HTTP clients use the sidecar without
provider-specific code changes. Docker-local PostgreSQL, Redis, and proxy
traffic remain direct.

The initial public-container-registry pull stalled on the deployment host. To
avoid making provider egress dependent on that pull, the deployment builds
`dotamind-vless-proxy:local` from the already present `dotamind-api` image and
an ignored static `deploy/sing-box/sing-box` binary. The binary was copied from
the existing VLESS server and verified with SHA-256 before installation.

Required server-only files:

```text
deploy/sing-box.client.json  # VLESS/Reality credentials; root:root, mode 600
deploy/sing-box/sing-box     # static executable; ignored deployment asset
```

The repository contains only
`deploy/sing-box.client.example.json` and `deploy/sing-box/Dockerfile`.

## Cutover validation

Before API recreation, an explicit request through the sidecar completed the
four PandaScore requests in 4.831 seconds:

| Request | Duration |
| --- | ---: |
| Series, `page[size]=100` | 2.583 s |
| upcoming | 0.371 s |
| running | 0.679 s |
| past | 1.199 s |

After recreating the API, the unchanged production transport relied only on its
environment proxy variables and completed the same sequence in 5.614 seconds.
After WireGuard removal, a final Series request completed in 3.399 seconds with
HTTP 200. The API and `vless-proxy` containers remained Up, and the VLESS
service on `96.126.130.87` remained active.

## WireGuard retirement

After the VLESS route was validated, `wg-quick@wg0` was stopped and disabled on
both hosts. The following verified WireGuard files were deleted:

- `106.52.89.125`: `wg0.conf`, `wg0.full-tunnel.conf`, `wg0.key`, `wg0.pub`.
- `96.126.130.87`: `wg0.conf`, `wg0.key`, `wg0.pub`.

Both post-cutover hosts reported no `wg0` interface. Recreating WireGuard now
requires a new configuration and key material; no compatibility route remains.

## Operations and non-goals

- Keep `vless-proxy` private to the Compose network; do not publish port 7890.
- When updating sing-box, verify the source, version, mode, and SHA-256 of the
  replacement deployment binary before rebuilding `vless-proxy`.
- Validate outbound provider calls from inside `dotamind-api-1`, not only from
  the host or a developer laptop.
- This migration does not remove the remaining application-level latency work:
  narrowing competition resolution, concurrent fixture endpoints, and
  cross-call caching remain separate, optional optimizations.
