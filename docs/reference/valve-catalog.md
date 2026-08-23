# Valve Catalog Reference

## Role

Valve Catalog supplies static hero, ability, item, and recipe facts. It is the
source for explaining Dota entities that appear in professional matches.

## Snapshot boundary

The catalog is a committed, versioned snapshot generated from official Valve
data in English and Simplified Chinese. Request-time lookup is offline and
read-only: it loads validated catalog entities rather than calling an upstream
service or falling back to unrelated constants.

## Data requirements

- Preserve stable IDs, references, tokens, and manifest counts during sync.
- Normalize bilingual display data and preserve the snapshot version.
- Keep unresolved or unclassified source material outside user-facing resolution.
- Return immutable or copied records so one request cannot mutate catalog state.
- Use origin-relative asset paths only; do not expose server filesystem paths.

## Maintenance

Catalog regeneration is a reviewed maintenance operation. Validate the complete
snapshot and inspect its diff before accepting updated runtime data. The vNext
implementation may reuse this knowledge only after confirming that the existing
snapshot format and sync path remain worth keeping.
