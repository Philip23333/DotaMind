# DotaMind vNext Documentation

DotaMind is a Dota 2 esports agent. These documents define the vNext target;
code may temporarily lag a target during an explicit migration.

## Read in order

1. `PRODUCT.md`
2. `ARCHITECTURE.md`
3. `ARTIFACTS.md` for Artifact externalization, corpus, and simplification
4. `TOOLS.md`
5. `DATA.md`
6. `EVALS.md`
7. `ROADMAP.md`

`reference/` contains provider and cross-source facts that were costly to
establish. It is supporting material, not product or architecture authority.

## Document ownership

Each long-term fact has one primary owner.

| Question | Owner |
| --- | --- |
| What DotaMind does and excludes | `PRODUCT.md` |
| Layer responsibilities and system boundaries | `ARCHITECTURE.md` |
| Why Artifacts exist, their corpus contract, and Artifact migration | `ARTIFACTS.md` |
| Agent-visible capabilities | `TOOLS.md` |
| Identity, providers, canonical data, catalog, and schema semantics | `DATA.md` |
| Behavioral and integration acceptance | `EVALS.md` |
| Delivery order | `ROADMAP.md` |
| Costly external implementation facts | `reference/` |

## Source of truth

- Code describes CURRENT behavior.
- The core documents describe the vNext TARGET.
- During a deliberate migration, a target document may describe behavior not yet
  implemented; do not treat transitional code as the long-term contract.
- `ARTIFACTS.md` is authoritative for the current Artifact simplification. Where
  older implementation-oriented text conflicts with it, follow `ARTIFACTS.md`
  and update the conflicting core document rather than preserving a second
  design.
- Git history and tags retain implementation history; the documentation tree
  should not become a progress archive.
