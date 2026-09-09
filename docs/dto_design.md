# DotaMind Esports DTO Design

> Status: DTO Design Frozen  
> Scope: PandaScore-backed Dota 2 esports domains  
> Provider query contract: see `docs/pandascore_dota_contract_baseline.md`

## 1. Purpose

This document defines the DotaMind DTOs produced after PandaScore responses cross the Domain Boundary.

DTOs are not mirrors of PandaScore OpenAPI models. They exist to:

- represent DotaMind domain facts;
- remove provider-specific representation details;
- make current vs historical relationship semantics explicit;
- avoid recursive or duplicated nested resource graphs;
- provide strict projected results for Artifact processing.

Data flow:

```text
PandaScore raw response
    ↓
explicit response mapper
    ↓
DotaMind DTO
    ↓
Artifact processor
    ↓
bounded model observation
```

Artifact stores the complete projected DotaMind result, not the raw PandaScore payload.

## 2. Global DTO Rules

### 2.1 Query DTO and Entity DTO are separate

Query DTOs describe how to find an entity. Entity DTOs describe what the entity is.

Pagination, filters, and search terms never belong to entity DTOs.

### 2.2 Domain DTOs are strict

All DotaMind-owned DTOs use:

```python
model_config = ConfigDict(extra="forbid")
```

Provider-side parsing may be tolerant, but the Domain Boundary must construct DTOs explicitly.

Rule:

```text
Provider side tolerant
Domain side strict
```

New PandaScore fields must not leak into model-facing results automatically.

### 2.3 Mappers do not perform extra HTTP lookups

A response mapper only transforms the provider response already available.

It must not call another endpoint to enrich a DTO. Missing cross-entity information is resolved through explicit tool calls.

### 2.4 Collections are always lists

Use:

```python
Field(default_factory=list)
```

not nullable collections.

```text
[]
→ no relation data in the current result
```

### 2.5 Search response anomalies

Every esports search response uses the same envelope:

```text
items
page
limit
anomalies
```

`anomalies` contains only model-visible mapping problems observed in the
current provider response. Normal missing data is represented by `None` or
`[]` and does not create an anomaly. A malformed local item may be skipped
while valid items continue to return. If the top-level provider response is
not a collection, the provider protocol error remains fatal.

## 3. Naming Convention

### Entity DTOs

```text
LeagueDTO
SeriesDTO
TournamentDTO
MatchDTO
TeamDTO
PlayerDTO
```

Pattern:

```text
<Entity>DTO
```

### Lightweight entity references

Create these only when there is a real embedded-relation consumer.

Current shared reference:

```text
TeamRefDTO
```

Do not mechanically create `LeagueRefDTO`, `SeriesRefDTO`, or `PlayerRefDTO` without a concrete consumer.

### Contextual relation DTOs

Use relationship/context names rather than vague names such as `SummaryDTO`, `IdentityDTO`, `LiteDTO`, or `CompactDTO`.

Current relation DTOs:

```text
TournamentParticipantDTO
TournamentRosterPlayerDTO
MatchParticipantDTO
MatchGameDTO
CurrentRosterPlayerDTO
```

## 4. PlayerRole

PandaScore may return Player role as integers, numeric strings, or mixed
position notation such as `"1/2"`.

DotaMind normalizes both into a domain enum:

```python
class PlayerRole(str, Enum):
    carry = "carry"
    mid = "mid"
    offlane = "offlane"
    soft_support = "soft_support"
    hard_support = "hard_support"
```

Mapping:

```text
1 / "1" → (carry,)
2 / "2" → (mid,)
3 / "3" → (offlane,)
4 / "4" → (soft_support,)
5 / "5" → (hard_support,)

"1/2" → (carry, mid)
"3/4" → (offlane, soft_support)
"4/5" → (soft_support, hard_support)
```

The adapter parses provider position notation and preserves its order while
normalizing it into one or more DotaMind semantic roles. A mixed value is
accepted only when every position token is recognized; an invalid token rejects
the complete role rather than producing a partial guess.

```text
Python domain value: (PlayerRole.carry, PlayerRole.mid)
Model-facing JSON:   ["carry", "mid"]
```

`None` means PandaScore did not provide a trusted role and does not emit a
warning. Invalid values such as `0`, `6`, `True`, `"carry"`, `"1/6"`, or
`"1/x"` map to `None` and emit a warning. The names `carry`, `mid`, `offlane`,
`soft_support`, and `hard_support` are DotaMind semantic normalization; they do
not claim to be PandaScore's raw position field values.

## 5. TeamRefDTO

`TeamRefDTO` is a lightweight readable reference to a Team.

It does not carry roster time semantics.

```python
class TeamRefDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str

    acronym: str | None = None
    location: str | None = None
    slug: str | None = None
    image_url: str | None = None
```

Consumers:

```text
series.teams result
TournamentParticipantDTO.team
MatchParticipantDTO.team
MatchDTO.winner
PlayerDTO.current_team
```

Explicitly excluded:

```text
players
modified_at
dark_mode_image_url
current_videogame
```

In particular, `players[]` must not appear in `TeamRefDTO`, otherwise historical Match or Tournament results could accidentally embed a Team's current roster.

## 6. LeagueDTO

```python
class LeagueDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    slug: str | None = None
    image_url: str | None = None
```

Removed:

```text
url
modified_at
videogame
series[]
```

`series[]` is navigation-only. Traverse explicitly with:

```text
series.search(league_id=...)
```

## 7. SeriesDTO

```python
class SeriesDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    league_id: int

    name: str | None = None
    full_name: str | None = None

    year: int | None = None
    season: str | None = None

    begin_at: datetime | None = None
    end_at: datetime | None = None

    winner_id: int | None = None
    tier: str | None = None

    slug: str | None = None
```

`name` and `full_name` remain separate. No synthetic `display_name` is introduced.

Known provider normalization:

```text
Series.name == ""
→ None
```

Removed:

```text
winner_type
modified_at
league {}
tournaments[]
videogame
videogame_title
```

Tournament traversal:

```text
tournament.search(series_id=...)
```

Series Team participation:

```text
series.teams(series_id=...)
→ list[TeamRefDTO]
```

This relation expresses historical Series-Team participation only and does not carry current Team players.

## 8. TournamentRosterPlayerDTO

This DTO is used only inside:

```text
TournamentParticipantDTO.expected_roster
```

It represents Player identity inside a Tournament-context historical/expected roster relation.

```python
class TournamentRosterPlayerDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str

    first_name: str | None = None
    last_name: str | None = None
    nationality: str | None = None

    slug: str | None = None
```

Explicitly excluded:

```text
active
role
age
birthday
modified_at
current_team
image_url
```

Reason: the historical roster membership relation is useful, but embedded Player attributes have not been shown to be historical snapshots. Historical Tournament payloads can contain current-like fields such as modern `modified_at`, `active`, or role values.

Therefore:

```text
historical/contextual membership relation
→ usable

embedded current-like Player attributes
→ not treated as historical facts
```

## 9. TournamentParticipantDTO

```python
class TournamentParticipantDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team: TeamRefDTO
    expected_roster: list[TournamentRosterPlayerDTO] = Field(
        default_factory=list
    )
```

Semantics:

```text
team
→ Team participating in this Tournament/stage

expected_roster
→ PandaScore Tournament-context expected roster for that Team
```

`expected_roster` is not evidence of the exact starting lineup for every Match.

## 10. Tournament Provider Normalization

PandaScore exposes both:

```text
teams[]
expected_roster[]
```

Testing shows that in current Dota 2 samples:

```text
teams[].id
≈
expected_roster[].team.id
```

but this is not treated as a guaranteed provider invariant.

DotaMind therefore normalizes both into:

```text
TournamentDTO.participants[]
```

### 10.1 Union rule

```text
participants.team.id
=
union(
    teams[].id,
    expected_roster[].team.id,
)
```

### 10.2 Team data precedence

If the same Team exists in both provider collections:

```text
TeamRefDTO
→ construct from teams[] first
```

`expected_roster[].team` is the fallback source.

Reason:

```text
teams[]
→ Tournament participation primary data

expected_roster[]
→ roster enrichment data
```

This precedence does not imply that `expected_roster.team` is untrustworthy; it only defines deterministic construction semantics.

### 10.3 Example

Provider:

```text
teams:
A
B
C

expected_roster:
A → players [...]
B → players [...]
D → players [...]
```

DotaMind:

```text
participants:
A → expected_roster [...]
B → expected_roster [...]
C → expected_roster []
D → expected_roster [...]
```

This prevents Team participation from disappearing when roster data is incomplete, while also preserving roster-only Team data if it appears.

### 10.4 Ordering

Ordering must be deterministic:

```text
1. preserve teams[] order
2. append expected_roster-only Teams afterward
```

Do not use an unordered set representation that can randomly reorder participants.

These rules are part of `TournamentDTO.participants` construction semantics and are frozen with the DTO design.

## 11. TournamentDTO

```python
class TournamentDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    series_id: int
    league_id: int

    name: str
    type: str | None = None

    country: str | None = None
    region: str | None = None

    begin_at: datetime | None = None
    end_at: datetime | None = None

    winner_id: int | None = None

    tier: str | None = None
    prizepool: str | None = None
    has_bracket: bool | None = None

    slug: str | None = None

    participants: list[TournamentParticipantDTO] = Field(
        default_factory=list
    )
```

Provider naming normalization:

```text
serie_id
→ series_id
```

Removed:

```text
winner_type
modified_at
detailed_stats
live_supported
serie {}
league {}
matches[]
videogame
videogame_title
```

Match traversal:

```text
match.search(tournament_id=...)
```

## 12. MatchParticipantDTO

PandaScore exposes Match Teams and scores separately through:

```text
opponents[]
results[]
```

DotaMind joins them so the model does not need to perform an ID join itself.

```python
class MatchParticipantDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    team: TeamRefDTO
    score: int | None = None
```

Semantics:

```text
team
→ Team participating in the Match

score
→ Match score for this Team when the provider supplied a result
```

Important distinction:

```text
score = None
→ no matching provider result

score = 0
→ provider explicitly returned zero
```

## 13. Match Participant Normalization

Provider:

```text
opponents[]
+
results[]
```

Domain:

```text
participants[]
```

Join key:

```text
opponent.id
↔
result.team_id
```

`opponents[]` is the participant identity source because `results[]` only contains `team_id` and score.

If a result contains a Team ID with no matching opponent object:

```text
→ emit warning / telemetry
→ do not invent a TeamRefDTO
```

Unlike Tournament normalization, this is not an unconditional union.

## 14. MatchGameDTO

```python
class MatchGameDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    position: int
    status: str

    begin_at: datetime | None = None
    end_at: datetime | None = None
    length: int | None = None

    winner_id: int | None = None

    complete: bool
    forfeit: bool
```

Provider normalization:

```text
game.winner.id
→ winner_id
```

Removed:

```text
match_id
finished
detailed_stats
winner_type
winner {}
```

`finished` is intentionally excluded. `status + complete` remain.

## 15. MatchDTO

```python
class MatchDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    slug: str | None = None

    status: str
    match_type: str | None = None
    number_of_games: int | None = None

    begin_at: datetime | None = None
    end_at: datetime | None = None

    scheduled_at: datetime | None = None
    original_scheduled_at: datetime | None = None

    league_id: int | None = None
    series_id: int | None = None
    tournament_id: int | None = None

    participants: list[MatchParticipantDTO] = Field(
        default_factory=list
    )

    winner_id: int | None = None
    winner: TeamRefDTO | None = None

    games: list[MatchGameDTO] = Field(
        default_factory=list
    )

    draw: bool
    forfeit: bool
    rescheduled: bool
```

### Winner

Both are retained:

```text
winner_id
winner
```

`winner_id` is the structured Team relation. `winner` is the readable Team reference already present in the same provider response.

If PandaScore supplies `winner_id` but no winner object, the DTO may contain:

```text
winner_id != null
winner = None
```

The mapper must not perform a Team lookup to fill it.

Removed:

```text
modified_at
league {}
serie {}
tournament {}
winner_type
opponents[]
results[]
videogame
videogame_title
videogame_version
streams_list
live
detailed_stats
game_advantage
```

`opponents[] + results[]` are replaced by `participants[]`.

## 16. Canceled Match Scores

If PandaScore explicitly returns:

```text
status = canceled
score = 0 : 0
```

DotaMind preserves the provider score values.

The mapper must not rewrite explicit zero scores to `None` merely because the Match is canceled.

Representation normalization is allowed; changing provider facts is not.

## 17. CurrentRosterPlayerDTO

This DTO is used only in:

```text
TeamDTO.current_roster
```

It represents a Player inside the Team's current membership snapshot.

```python
class CurrentRosterPlayerDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str

    active: bool
    role: tuple[PlayerRole, ...] | None = None

    first_name: str | None = None
    last_name: str | None = None
    nationality: str | None = None

    slug: str | None = None
    image_url: str | None = None
```

Because Team `players[]` has been verified as a current snapshot, current `active` and `role` are safe to expose here.

This is intentionally different from `TournamentRosterPlayerDTO`.

## 18. TeamDTO

```python
class TeamDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str

    acronym: str | None = None
    location: str | None = None
    slug: str | None = None
    image_url: str | None = None

    current_roster: list[CurrentRosterPlayerDTO] = Field(
        default_factory=list
    )
```

Provider:

```text
players[]
```

DotaMind:

```text
current_roster[]
```

The field name intentionally encodes time semantics.

Verified meaning:

```text
Team.players[]
→ current Team membership snapshot
```

Removed:

```text
modified_at
dark_mode_image_url
current_videogame
```

## 19. PlayerDTO

```python
class PlayerDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str

    active: bool
    role: tuple[PlayerRole, ...] | None = None

    first_name: str | None = None
    last_name: str | None = None
    nationality: str | None = None

    slug: str | None = None
    image_url: str | None = None

    current_team: TeamRefDTO | None = None
```

Semantics:

```text
PlayerDTO
→ current Player entity state

current_team
→ current Team relation

active
→ Player's own current active state
```

`current_team` is not historical Team membership.

Removed:

```text
modified_at
current_videogame
age
birthday
```

`birthday` is intentionally not part of `PlayerDTO` because it has not been verified in the top-level `/dota2/players` response contract, even though it appears in some nested Player representations.

## 20. Current vs Historical Semantics

```text
TeamDTO.current_roster
→ current Team membership
→ CurrentRosterPlayerDTO
```

```text
PlayerDTO.current_team
→ current Team relation
```

```text
player.search(team_id=...)
→ current Team membership
```

versus:

```text
Series → Team
→ historical Series-Team participation
→ TeamRefDTO
```

versus:

```text
TournamentParticipantDTO.expected_roster
→ Tournament-context historical/expected roster membership
→ TournamentRosterPlayerDTO
```

Match relations are intrinsic to that Match:

```text
MatchParticipantDTO
MatchGameDTO
MatchDTO.winner
```

These relationship semantics must not be substituted for each other.

## 21. Text Normalization

Optional metadata fields may normalize:

```text
null      → None
""        → None
"   "     → None
" value " → "value"
```

Typical candidates:

```text
slug
acronym
location
first_name
last_name
nationality
season
tier
```

Core display names should not receive unverified semantic rewriting.

Known accepted exception:

```text
Series.name == ""
→ None
```

## 22. Parent Resource Normalization

Normalize provider naming:

```text
serie_id
→ series_id
```

Complete parent objects are not retained in child DTOs:

```text
league {}
serie {}
tournament {}
```

Navigation is performed using parent IDs.

## 23. DTO Dependency Graph

```text
PlayerRole
├── PlayerDTO
└── CurrentRosterPlayerDTO

TeamRefDTO
├── PlayerDTO.current_team
├── TournamentParticipantDTO.team
├── MatchParticipantDTO.team
└── MatchDTO.winner

TournamentRosterPlayerDTO
└── TournamentParticipantDTO
    └── TournamentDTO

CurrentRosterPlayerDTO
└── TeamDTO

MatchParticipantDTO
┐
├── MatchDTO
┘
MatchGameDTO
```

There is no DTO recursion.

## 24. Do Not Use DTO Inheritance for Shared Fields

Do not couple contracts through inheritance merely to remove a few repeated fields.

For example, avoid:

```python
class TeamDTO(TeamRefDTO):
    current_roster: ...
```

`TeamDTO` and `TeamRefDTO` are separate contracts with different evolution pressure.

A small amount of explicit field duplication is preferred over inheritance coupling.

## 25. Final DTO Inventory

Frozen DTOs:

```text
LeagueDTO
SeriesDTO
TournamentDTO
TournamentParticipantDTO
TournamentRosterPlayerDTO
MatchDTO
MatchParticipantDTO
MatchGameDTO
TeamDTO
TeamRefDTO
CurrentRosterPlayerDTO
PlayerDTO
PlayerRole
```

Not currently created:

```text
LeagueRefDTO
SeriesRefDTO
PlayerRefDTO
```

## 26. Final Domain Normalization Summary

```text
PandaScore serie_id
→ DotaMind series_id
```

```text
PandaScore Player role int/string
→ DotaMind PlayerRole
```

```text
Tournament:
teams[]
+
expected_roster[]
→ participants[]
```

```text
Match:
opponents[]
+
results[]
→ participants[]
```

```text
Match winner {}
→ TeamRefDTO
```

```text
Game winner {}
→ winner_id
```

```text
Team players[]
→ current_roster[]
```

```text
Provider nested objects
→ explicit projection only
```

```text
Mapper
→ no additional HTTP lookup
```

## 27. Design Principle

DTO design starts from:

> What does this information mean to DotaMind?

not:

> What fields happen to exist in the PandaScore response?

Boundary responsibilities remain separate:

```text
Provider Boundary
→ How do we ask PandaScore?

Domain Boundary / DTO
→ What does this information mean to DotaMind?

Context Boundary / Artifact
→ How much of the DotaMind result should the model observe at once?
```
