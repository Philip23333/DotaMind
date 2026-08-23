# 2026-08-23 Progress Snapshot

## 16:09 — VLESS provider-egress migration preparation

### Completed

- Production Compose now defines an internal `vless-proxy` sing-box sidecar; the API uses its internal HTTP inbound through standard `HTTP_PROXY` / `HTTPS_PROXY`, while `NO_PROXY` keeps Compose-local services direct.
- Added a credential-free sing-box client example; the real `deploy/sing-box.client.json` is ignored, retained only on the deployment host, and protected with root-owned mode 600.
- Reproduced the slow direct PandaScore path inside the real API container on 106.52.89.125: the 100-row Series request took about 20.27 seconds and the sequential fixture listing about 14.62 seconds, including about 11.44 seconds for `past`; the container has no proxy environment variables.
- The VLESS server already exists on 96.126.130.87; the private client JSON was written on 106, passed JSON syntax validation, and the production Compose structure was backed up and validated.

### Verification

- Local Compose structural validation for `compose.prod.yml` and JSON validation for `deploy/sing-box.client.example.json` passed.
- Production `docker compose config -q` on 106 passed; the private client configuration is `root:root`, mode 600.

### Current limitation

- The `ghcr.io/sagernet/sing-box:v1.13.16` image is still downloading in the background on 106; the sidecar is not ready, the API has not been recreated, and WireGuard remains running on both hosts.
- Sidecar connectivity, PandaScore latency validation through VLESS, and WireGuard removal must be completed in that order once the image is ready.

## 16:21 — VLESS egress active and WireGuard retired

### Completed

- Because the sing-box image pull from GHCR stalled on 106, the deployment now uses a SHA-256-verified static sing-box binary from the existing service on 96 and builds the `dotamind-vless-proxy:local` sidecar locally from the pre-existing `dotamind-api` image; it no longer depends on an external image pull.
- `vless-proxy` runs only on the Compose network and exposes no public port; after API recreation, standard `HTTP_PROXY` / `HTTPS_PROXY` variables point it to that sidecar.
- Stopped and disabled `wg-quick@wg0` on 106.52.89.125 and 96.126.130.87, then removed the verified `wg0` configuration, full-tunnel configuration, and WireGuard key files.

### Verification

- API-container pre-cutover VLESS timing for the four requests: 2.58 seconds for the 100-row Series request, 0.37 seconds for upcoming, 0.68 seconds for running, 1.20 seconds for past, and 4.83 seconds total.
- After API recreation, the same four requests using only environment-provided proxy routing took 5.61 seconds; the runtime environment contains `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY`.
- After WireGuard cleanup: neither host has a `wg0` interface; `sing-box-vless` is active on 96; both the API and `vless-proxy` are Up on 106; a final API Series request took 3.40 seconds and returned HTTP 200.

### Known boundary

- Deployment-side `deploy/sing-box/sing-box` and `deploy/sing-box.client.json` are ignored server assets and never enter Git; future sing-box updates must revalidate binary provenance and version.

## 16:38 — PandaScore egress diagnosis and VLESS migration technical record

### Completed

- Added `docs/technical/pandascore_egress_migration_2026-08-23.md`, consolidating the tool-call topology, container-direct reproduction, VLESS sidecar structure, local-build workaround for the stalled image pull, before/after latency, WireGuard retirement scope, and operational boundaries.
- Registered the record in the technical reference section of `docs/README.md`; the document contains no VLESS UUID, Reality parameters, private JSON, or static binary.

### Verification

- Checked relative links in the technical record and documentation navigation; the Chinese and English progress snapshots add this section with the same structure.
