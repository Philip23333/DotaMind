# Tools

## Design rules

Agent-visible tools describe broad observation capabilities. They are not a
mirror of provider endpoints and not an ontology-shaped API where every
League/Series/Tournament/Match object gets its own tool family.

The model owns ordinary reasoning and decides which capabilities to compose.
Provider implementations stay below the tool boundary; provider names remain
visible as provenance in results.

Different providers implementing the same capability may return different
source-shaped fact payloads. DotaMind should not invent a field-by-field
universal DTO unless a concrete cross-source consumer requires one.

Large complete results stay outside model context. A capability may persist the
complete validated result as an Artifact, return only bounded facts plus an
`ArtifactRef`, and let the model use generic Artifact search/read when useful.

No tool description should prescribe a fixed workflow or claim that a locator
must have come from one specific preceding tool.

## Current implemented surface

The current branch exposes these migration-era tools:

| Tool | Current purpose | Target disposition |
| --- | --- | --- |
| `esports.search` | Navigate PandaScore-backed esports source facts | Retain as the broad discovery capability |
| `matches.get_detail` | Transitional SourceLocator-to-detail bridge | Replace with `game.detail` |
| `teams.search` / `teams.get_detail` | Team discovery/detail | Keep during this migration; revisit only when another source requires it |
| `players.search` / `players.get_detail` | Player discovery/detail | Keep during this migration; revisit only when another source requires it |
| `artifact.search` | Exact stored Artifact availability lookup | Retain |
| `artifact.grep` | Generic Artifact content search | Retain |
| `artifact.read` | Generic bounded Artifact read | Retain |

The old `series.search`, `series.list_matches`, and `matches.search` tools are
no longer model-visible. Their Ref-based internals remain only where the
transitional detail and Artifact path still needs them.

## Target capability surface

### `esports.search`

Purpose: search the esports/event/match fact space without exposing one tool per
provider object type.

Current implementation: PandaScore.

Future implementations: any source that can provide esports discovery. A new
source joins this capability instead of creating a parallel provider-named tool
tree by default.

The initial contract should stay small. Conceptually useful inputs are:

```text
query        optional user text
within       optional SourceLocator
teams        optional exact PandaScore team-name constraint
time_scope   optional bounded temporal scope
limit        bounded result count
```

The exact first-version input should be no broader than demonstrated evals
require.

A result record uses a thin envelope:

```text
source
kind
locator
facts
```

For PandaScore, `kind` may be its own vocabulary such as `league`, `series`,
`tournament`, `match`, or `game`. Another source may use different terms.

`facts` are bounded, validated, source-backed facts. They do not need to fit a
universal League/Series/Tournament/Match DTO.

An optional `within` locator lets the same broad search capability continue
inside a source object. The current PandaScore implementation supports:

```text
league -> series
series -> match
match  -> game
```

Unknown locators, a locator from another source, and locator-kind mismatches are
explicit tool errors; they are not equivalent to an empty search result. The
model does not need a separate `series.list_matches` tool.

The first implementation does not need a provider-routing framework or explicit
model-selected source list. With only PandaScore configured, `esports.search`
simply uses it. If a second implementation arrives, add the smallest aggregation
or source-selection rule justified by real use.

### `game.detail`

Purpose: obtain detailed recorded-game facts after a game is identified.

Current detail implementation: OpenDota.

The capability may accept either:

- a canonical `valve_match_id` when already known; or
- a `SourceLocator` for a discovered source object that can be deterministically
  resolved to a Valve match identity.

Current composition remains internal:

```text
PandaScore locator
  -> deterministic PandaScore-to-Valve resolver
  -> valve_match_id
  -> OpenDota detail implementation
```

The tool returns bounded source-attributed facts. If the complete detail is
large, it is stored as an Artifact and the result includes an `ArtifactRef`.

If another game-detail source is added later, `game.detail` may return multiple
source-attributed detail results or use an explicit selection policy. Do not
merge different detail schemas into one synthetic universal object merely to
share the tool name.

## SourceLocator

A `SourceLocator` is the reusable locator for a provider-backed source object.
Conceptually:

```json
{
  "source": "pandascore",
  "kind": "series",
  "value": "opaque:..."
}
```

The raw PandaScore/provider resource ID remains internal. The locator means
"this object in this source"; it is not a claim that DotaMind has established a
cross-source canonical Series/Match identity.

A locator returned by one capability may be passed to any capability that
explicitly accepts a `SourceLocator`. Tool descriptions should describe the
accepted locator semantics, not name one mandatory producing tool.

## Source attribution and failure

When several provider implementations eventually participate in one capability,
results remain source-attributed.

A provider failure must remain distinguishable from:

- no result in another source;
- an ambiguous source object;
- failed source-to-Valve resolution;
- missing Artifact data.

Do not silently fall back to another provider and present the result as though it
came from the failed source.

## Catalog capabilities

Static Valve ID translation is a separate fact space:

| Tool | Purpose | Boundary |
| --- | --- | --- |
| `catalog.search` | Resolve human-facing hero/item/ability text to Valve-native candidates | Local static catalog only |
| `catalog.lookup` | Batch-resolve Valve-native IDs to names/localization/reference facts | Local deterministic lookup; no provider call |

Dynamic game-detail results may keep `hero_id`, `item_id`, and `ability_id` as
plain Valve-native facts. The model uses Catalog when it needs readable static
meaning.

Do not create separate `catalog.get_hero`, `catalog.get_item`, and
`catalog.get_ability` tools unless the two generic capabilities prove
insufficient.

## Artifact tools

Artifact exploration remains generic and provider-blind:

| Tool | Purpose | Boundary |
| --- | --- | --- |
| `artifact.search` | Exact stored-document availability lookup | No provider fetch or production |
| `artifact.grep` | Literal/schema-neutral scalar search over stored documents | Returns ArtifactRef + structural path + preview |
| `artifact.read` | Bounded structural read | Exact ArtifactRef/path; no provider semantics |

A new source-backed Artifact becomes searchable because it is a JSON-like stored
document, not because a provider-specific search adapter is added.

Future generic path constraints are acceptable when real usage requires them.
Business dimensions such as hero, player, build, PandaScore Series, or OpenDota
player schema do not belong in the Artifact-search contract.

## Provider implementation rule

Prefer:

```text
esports.search
  -> PandaScore implementation

game.detail
  -> OpenDota implementation
```

over:

```text
pandascore.search_series
pandascore.list_matches
opendota.get_match
future_provider.get_match
```

The provider implementation may use source-specific methods internally. The
model should see the broad fact-space capability unless provider-specific
behavior itself becomes a genuine user-facing need.

## Rejected tool shapes

Do not add:

- `league.search` merely because PandaScore has League objects;
- separate Series/Tournament/Match tool families to mirror PandaScore;
- one model-facing provider namespace per source by default;
- a universal cross-provider esports DTO as a prerequisite for search;
- a universal cross-provider game-detail DTO as a prerequisite for detail;
- `artifact.find_player_hero_games`, `artifact.find_build`, or similar scenario
  helpers;
- a model-facing `artifact.produce` tool for ordinary detail externalization;
- a provider router/plugin framework before a second implementation requires it.
