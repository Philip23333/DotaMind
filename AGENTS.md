# Project Direction

This branch starts the DotaMind vNext clean-slate rewrite. The Legacy V3
baseline is frozen at the Git tag pre-vnext-rewrite.

Before architecture or product work, read:

1. docs/PRODUCT.md
2. docs/ARCHITECTURE.md
3. docs/TOOLS.md
4. docs/DATA.md
5. docs/EVALS.md
6. docs/ROADMAP.md when the work belongs to a planned phase

The current code is Legacy until it is deliberately replaced. The documents
describe vNext TARGET architecture. Do not treat old code as a vNext
compatibility contract.

# Architecture Rules

- The model owns normal business reasoning and decides when to use domain tools.
- Do not add scenario-specific workflows, routers, or prompt recipes.
- Do not introduce an ExecutionPlan DSL, model-authored evidence obligations, or
  provider-visible tool orchestration.
- Agent-visible tools express independent domain capabilities; provider ID
  conversion, cross-source mapping, and normalization stay below the tool layer.
- Scenario-specific behavior belongs in EVALS.md, not in runtime branches.
- Deterministic code protects validation, identity, authorization, transport,
  timeout, cancellation, persistence, and data integrity boundaries.
- Prefer deletion over compatibility shims when replacing Legacy behavior.

# Development Rules

- Verify the current working tree and relevant tests before changing behavior.
- Do not add fallback or mock behavior that hides missing integrations or errors.
- Network and provider-SDK calls belong only in provider adapters. Domain
  services orchestrate those adapters and never call upstream APIs directly.
- Run focused tests for every behavior change and report only checks that ran.
- Update a core document only when its long-term product or architecture contract
  changes. Do not maintain daily progress snapshots or an in-repository archive;
  Git history, commits, and tags hold implementation history.
- Keep reference/ for facts that are expensive to rediscover from providers or
  cross-source testing. Revalidate volatile provider facts before relying on them.
