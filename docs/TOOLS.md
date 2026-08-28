# Tools

## Design rules

Agent-visible tools are independent Dota capabilities. They expose facts,
locators, bounded reads, and small deterministic reference lookups; they do not
encode a complete user-scenario workflow.

The model owns ordinary reasoning and decides which capabilities to compose.
Provider-private identifier conversion, provider transport, and cross-source
match resolution stay below the tool layer. Canonical Valve-native IDs are
ordinary Dota facts and may be model-visible where useful.

Large results should not be copied wholesale into model context. A capability
may externalize the complete canonical result as an Artifact, return a bounded
view plus `ArtifactRef`, and let the model use generic artifact discovery or
retrieval when it needs more detail.

No tool description requires a fixed sequence such as search -> detail -> read.

## Implemented domain and Artifact surface

The current implemented surface contains these independent capabilities:

| Tool | Purpose | Important contract |
| --- | --- | --- |
| `series.search` | Find an esports series or edition | Preserves candidate ambiguity |
| `series.list_matches` | List matches for a series | Returns bounded schedule facts |
| `matches.search` | Find professional matches | Does not guess a unique match |
| `matches.get_detail` | Return detail for a resolved match or game | Resolved games include `valve_match_id` and currently guarantee local Artifact production |
| `teams.search` | Find a professional team | Preserves ambiguity and returns opaque `TeamRef` locators |
| `teams.get_detail` | Return source-backed team facts | Accepts a `TeamRef` locator |
| `players.search` | Find a professional player | Preserves ambiguity and current-team identity when available |
| `players.get_detail` | Return source-backed player facts | Accepts a `PlayerRef` locator |
| `artifact.search` | Find stored GameSummary artifacts by exact Valve match identity | Existence lookup only; never reads or produces |
| `artifact.grep` | Search canonical Artifact scalar content | Optional opaque scope limits the materialized corpus only |
| `artifact.read` | Read a bounded canonical Artifact view | Exact `ArtifactRef`, structural path, bounded list pagination |

`matches.get_detail` production is an application/data boundary, not Agent
Runtime behavior. Artifact search/read never fetch providers or create missing
Artifacts.

## Target catalog surface

Static Dota catalog facts should be exposed through a very small model-facing
surface rather than duplicated into every dynamic Game Artifact.

| Tool | Purpose | Input | Output | Boundary |
| --- | --- | --- | --- | --- |
| `catalog.search` | Resolve user-facing hero/item/ability text to static catalog candidates | Query plus optional bounded type filter | Candidate Valve-native IDs and static names | Local catalog only; no gameplay interpretation |
| `catalog.lookup` | Batch-resolve Valve-native IDs to static catalog facts | Bounded hero/item/ability ID lists | Canonical static names/localization and available catalog facts | Local deterministic lookup; no provider call |

The intended composition is simple:

```text
User says "Earth Spirit" / "土猫"
  -> catalog.search
  -> hero_id
  -> Artifact exploration using the recorded ID

Artifact returns item_id / ability_id
  -> catalog.lookup
  -> readable static names
```

Do not add separate `catalog.get_hero`, `catalog.get_item`, and
`catalog.get_ability` tools unless real evaluations demonstrate that the two
small generic capabilities are insufficient.

## Artifact inspection tools

Artifact exploration is breadth-to-depth over a structured corpus:

| Tool | Inputs | Output | Boundary |
| --- | --- | --- | --- |
| `artifact.search` | Artifact type plus up to 100 canonical Valve match IDs | `refs` and ordered missing IDs | Existence checks only |
| `artifact.grep` | Literal pattern, optional opaque scope/type restriction, limit | `ArtifactRef`, structural path, preview, `coverage=materialized_only` | Schema-neutral scalar search; never fetches or produces |
| `artifact.read` | Exact `ArtifactRef`, optional dotted path, offset, limit | Outline or serialized bounded value | Generic structural read only |

A new Artifact type should become searchable because it is serialized into the
same generic document substrate, not because programmers implement a custom
search view for that type.

Future search refinements may add generic structural constraints such as path
selection if real usage requires them. They must not add business dimensions
such as hero, player, item, or tournament as Artifact-search-specific concepts.

## Ref rule

Refs are locators passed between capabilities, not wrappers for every Dota ID or
nested event.

Use refs for entities that another tool must locate again, for example Series,
Match, Game, Team, Player, or Artifact where those navigation needs exist.
Valve-native `hero_id`, `item_id`, `ability_id`, `valve_team_id`,
`steam_account_id`, and similar recorded facts do not need dedicated Ref
wrappers merely to enter an Artifact.

## Response boundaries

- Return bounded data by default.
- Make ambiguity, truncation, missing coverage, and provider failures explicit.
- Never expose provider-private PandaScore/OpenDota resource IDs as an agent
  language.
- Canonical Valve-native IDs may be returned as Dota facts.
- Do not copy a full large Artifact into a normal tool result.
- Do not create one tool per Artifact section or user question.
- Add a capability only when it exposes an independent fact-space or
  data-access need that generic composition cannot already satisfy.

## Rejected tool shapes

Do not add tools such as:

- `artifact.find_player_hero_games`
- `artifact.find_build`
- `artifact.find_skill_order`
- one Artifact-search adapter per schema
- one static catalog tool per entity type without demonstrated need
- a model-facing `artifact.produce` tool for ordinary match-detail production

The preferred model is a small set of orthogonal observation capabilities that
the model composes itself.
