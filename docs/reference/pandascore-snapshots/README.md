# PandaScore raw snapshots

Each dated directory contains bounded raw JSON responses captured with the
configured PandaScore account. `manifest.json` records the request path,
non-sensitive query parameters, and capture status for every file.

Snapshots deliberately exclude request headers and credentials. They are
provider observations, not a stable API contract, and should be refreshed when
an implementation needs to rely on a volatile field or endpoint.

Run this from `apps/api` to create a new UTC-dated capture:

```text
python -m scripts.capture_pandascore_reference
```

The collector samples every endpoint used by the current adapter with bounded
pages. `game` and `tournament` are recorded as nested values from a match detail
response because the adapter has no standalone request for either type.
