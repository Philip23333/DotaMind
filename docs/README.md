# DotaMind vNext Documentation

DotaMind is a Dota 2 esports agent. This directory defines the vNext target,
not a compatibility layer for the frozen Legacy V3 implementation.

## Status

The Legacy V3 baseline is preserved at Git tag `pre-vnext-rewrite`. Current code
may intentionally lag the target documents during an active migration; do not
preserve transitional vNext structure merely because it already exists.

## Read in order

1. `PRODUCT.md`
2. `ARCHITECTURE.md`
3. `TOOLS.md` and `DATA.md`
4. `ARTIFACTS.md` when work touches large-result externalization, Artifact
   storage, corpus search/read, or the current simplification migration
5. `EVALS.md`
6. `ROADMAP.md`

`reference/` contains provider and identity facts that were costly to establish.
It is supporting material, not product or architecture authority.

## Document ownership

Each long-term fact has one owner document; other documents link rather than
copy it.

| Question | Owner |
| --- | --- |
| What DotaMind does and excludes | `PRODUCT.md` |
| Layer and capability/provider boundaries | `ARCHITECTURE.md` |
| Agent-visible capability contracts | `TOOLS.md` |
| Source identity, locators, provider facts, Valve identity, and normalization | `DATA.md` |
| Large-result externalization, Artifact storage, corpus, and migration | `ARTIFACTS.md` |
| Behavioral and integration acceptance | `EVALS.md` |
| Delivery order | `ROADMAP.md` |
| Costly external implementation facts | `reference/` |

## Source of truth

- Code describes CURRENT behavior.
- The core documents above describe the vNext TARGET.
- When target documents and code differ during a planned migration, follow the
  documented target rather than adding compatibility structure around the old
  implementation.
- Git history and tags retain implementation history; this tree does not keep a
  daily progress archive.
