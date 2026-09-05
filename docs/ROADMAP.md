# Roadmap

## Guiding order

Work one capability boundary at a time:

```text
architecture confirmation
  -> one design unit
  -> implementation
  -> focused acceptance
  -> broader regression
```

Do not expand a capability into a provider-routing framework or universal DTO
before a second concrete implementation demonstrates the need.

## Commit 1: clean-slate tool layer

- Establish an artifact-only default model-facing registry baseline.
- Remove legacy domain tools, provider integrations, sample-policy mutation,
  provider prompt rules, and compatibility aliases.
- Preserve generic registry, executor, Controller, execution, tracing,
  persistence, and Artifact runtime primitives.

## Commit 2: semantic esports match search (implemented / under acceptance)

- Add the closed `esports.match.search` capability contract.
- Connect the contract to a thin PandaScore client and match adapter.
- Keep provider query syntax, transport details, and provider-private field
  names below the model-facing tool schema.
- Preserve complete validated match facts in the capability result without
  adding Artifact externalization to this first bounded implementation.
- Protect the input/output boundary, request mapping, endpoint selection, and
  registry inventory with focused tests.

## Commit 3: semantic esports league search (implemented / under acceptance)

- Add the closed `esports.league.search` capability for recurring competition
  identity discovery.
- Reuse the existing PandaScore client through a second thin league adapter.
- Keep edition, season, and provider-specific fields out of the league schema.
- Protect one-request mapping, strict `id`/`name` normalization, and the exact
  four-tool registry inventory with focused tests.

## Subsequent capability work

1. Define one closed semantic capability contract.
2. Add its provider implementation and complete source-backed document path.
3. Protect input/output schemas, bounds, source attribution, and failures with
   deterministic tests.
4. Register the capability only after its focused acceptance passes.
5. Remove transitional code once the replacement is accepted.

## Not planned in the baseline

- a complete domain tool suite before each capability contract is accepted;
- provider selection or routing machinery;
- a universal esports hierarchy or cross-provider DTO;
- hidden provider fetches from Artifact tools;
- scenario-specific workflows or prompt recipes;
- sample-size or provider-specific plan mutation.
