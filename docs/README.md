# DotaMind vNext Documentation

DotaMind is a Dota 2 esports agent. This directory defines the vNext target,
not a compatibility layer for the frozen Legacy V3 implementation.

## Status

The Legacy V3 baseline is preserved at Git tag pre-vnext-rewrite. The vNext
runtime foundation exists, while public API and domain capabilities still use
Legacy V3 until later migration phases.

## Read in order

1. PRODUCT.md
2. ARCHITECTURE.md
3. TOOLS.md and DATA.md
4. EVALS.md
5. ROADMAP.md

reference/ contains provider and identity facts that were costly to establish.
It is supporting material, not product or architecture authority.

## Document ownership

Each long-term fact has one owner document; other documents link rather than
copy it.

| Question | Owner |
| --- | --- |
| What DotaMind does and excludes | PRODUCT.md |
| Layer responsibilities and boundaries | ARCHITECTURE.md |
| Agent-visible capabilities | TOOLS.md |
| Identity, providers, normalization, and provenance | DATA.md |
| Behavioral and integration acceptance | EVALS.md |
| Delivery order | ROADMAP.md |
| Costly external implementation facts | reference/ |

## Source of truth

- Code describes CURRENT behavior.
- PRODUCT.md through ROADMAP.md describe the vNext TARGET.
- When a target document conflicts with code, correct the target document or
  implement the planned change. Do not create a second document to reconcile
  conflicting descriptions.
- Git history and tags retain Legacy V3 implementation history; this tree does
  not maintain an archive or daily progress log.
