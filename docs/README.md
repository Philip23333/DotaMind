# DotaMind vNext Documentation

DotaMind is a Dota 2 esports agent. This directory defines the vNext target,
not a compatibility layer for the frozen Legacy V3 implementation.

## Status

The Legacy V3 baseline is preserved at Git tag pre-vnext-rewrite. vNext
documentation is ready to guide the rewrite; vNext runtime code has not yet
replaced the Legacy implementation.

## Read in order

1. PRODUCT.md
2. ARCHITECTURE.md
3. TOOLS.md and DATA.md
4. EVALS.md
5. ROADMAP.md

reference/ contains provider and identity facts that were costly to establish.
It is supporting material, not product or architecture authority.

## Source of truth

- Code describes CURRENT behavior.
- PRODUCT.md through ROADMAP.md describe the vNext TARGET.
- When a target document conflicts with code, correct the target document or
  implement the planned change. Do not create a second document to reconcile
  conflicting descriptions.
- Git history and tags retain Legacy V3 implementation history; this tree does
  not maintain an archive or daily progress log.
