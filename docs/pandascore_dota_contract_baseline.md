# PandaScore → DotaMind Contract Baseline

> Status: Provider/Tool Contract Baseline Frozen  
> Scope: Dota 2 esports domains backed by PandaScore  
> DTO Status: Detailed DTO design intentionally **not frozen** in this document. DTOs will be reviewed domain by domain separately.

## 1. Purpose

This document records the verified boundary between PandaScore and DotaMind after direct API testing.

It freezes:

- model-facing tool input contracts;
- PandaScore adapter query mappings;
- verified filter/search/lifecycle semantics;
- cross-resource navigation semantics;
- current-vs-historical relationship semantics;
- response projection boundaries that have already been explicitly decided;
- known capability gaps.

It does **not** freeze the complete field-level DTO design for every domain.

Detailed DTO design will be discussed separately at the same domain granularity:

1. League
2. Series
3. Tournament
4. Match
5. Team
6. Player

The DTO discussion may further decide which intrinsic fields are retained, renamed, summarized, or removed, as long as it does not violate the contract and semantic boundaries frozen here.

---

# 2. Architecture Boundary

The expected data flow is:

```text
Model semantic query
    ↓
Closed DotaMind Tool Input Schema
    ↓
PandaScore Adapter / Query Compiler
    ↓
PandaScore HTTP API
    ↓
Raw PandaScore response
    ↓
Response Mapper / Domain Boundary
    ↓
DotaMind DTO / Domain Result
    ↓
Artifact Processor / Context Boundary
    ↓
Bounded model observation
```

There are three distinct boundaries.

## 2.1 Provider Boundary

Responsibilities:

```text
DotaMind semantic fields
    ↓
PandaScore-specific paths / query parameters
```

Examples:

```text
series_id → filter[serie_id]

team_id in match.search
→ filter[opponent_id]

winner_id
→ filter[winner_id]

limit
→ per_page
```

Provider terminology and quirks must not leak into the model-facing contract where a clearer DotaMind semantic name exists.

For example, the model should use:

```text
team_id
```

rather than PandaScore's:

```text
opponent_id
```

when the intended meaning is:

> matches involving this Team.

---

## 2.2 Domain Boundary

Responsibilities:

```text
Raw PandaScore response
    ↓
DotaMind-owned domain representation
```

This layer determines:

- which provider fields survive;
- which names are normalized;
- which nested relationships are retained;
- which navigation-only child resources are removed;
- which provider-only metadata is discarded;
- what the temporal semantics of embedded relationships are.

DotaMind DTOs are not intended to mirror PandaScore OpenAPI models.

---

## 2.3 Context Boundary

Responsibilities:

```text
Complete projected DotaMind result
    ↓
bounded model observation
```

Artifact belongs to this boundary.

Artifact is **not** a raw PandaScore response archive.

The intended flow is:

```text
PandaScore raw payload
    ↓
response mapper
    ↓
DotaMind DTO / projected result
    ↓
Artifact
```

Therefore:

> Fields removed by the Domain Boundary are intentionally unavailable to the model, including through Artifact.

Raw provider payloads may still exist in logs/debugging outside the model-facing context path.

---

# 3. General Contract Principles

## 3.1 Closed model-facing schemas

Each tool exposes an explicit set of semantic fields.

Undeclared PandaScore filters are not automatically exposed.

Provider capability alone is not sufficient reason to add a field to a DotaMind tool.

---

## 3.2 Search is discovery, not identity

Across the tested domains:

```text
search[name]
```

is fuzzy/discovery-oriented and may produce ambiguous candidate sets.

Therefore:

```text
search[name]
≠ exact identity
```

Known IDs should be preferred when available.

---

## 3.3 Multiple query conditions use AND semantics

Verified repeatedly across League, Series, Tournament, Match, Team, and Player.

Example:

```text
filter[id]=X
+
filter[parent_id]=Y
```

returns no result when the ID belongs to a different parent.

---

## 3.4 Navigation-only child collections are removed

General rule:

> A nested child collection whose primary purpose is navigating to another independently queryable resource should not automatically enter the parent domain result.

Examples already frozen:

```text
League.series[]
→ remove

Series.tournaments[]
→ remove

Tournament.matches[]
→ remove
```

However, nested relations that directly describe the resource's state or historical context may remain.

Examples:

```text
Tournament.teams[]
Tournament.expected_roster[]
Match.opponents[]
Match.results[]
Match.games[]
```

---

# 4. League Domain

## 4.1 Model-facing contract

```text
esports.league.search

id?
name?
page=1
limit=20
```

## 4.2 Provider mapping

```text
id
→ filter[id]

name
→ search[name]

page
→ page

limit
→ per_page
```

## 4.3 Verified semantics

`filter[id]` is exact.

`search[name]` is fuzzy/discovery-oriented.

Queries such as:

```text
search[name]=the
```

can return broad candidate sets.

Multiple conditions use AND semantics.

## 4.4 Frozen response boundary

PandaScore League contains a nested:

```text
series[]
```

collection.

This collection is navigation-only for DotaMind and must not enter the League domain result.

Navigation is explicit:

```text
League
→ series.search(league_id=...)
```

The exact final field composition of `LeagueDTO` remains a separate DTO-design decision.

---

# 5. Series Domain

## 5.1 Model-facing contract

```text
esports.series.search

id?
league_id?
name?
season?
year?
winner_id?
tier?
page=1
limit=20
```

## 5.2 Provider mapping

```text
id
→ filter[id]

league_id
→ filter[league_id]

name
→ search[name]

season
→ filter[season]

year
→ filter[year]

winner_id
→ filter[winner_id]

tier
→ filter[tier]

page
→ page

limit
→ per_page
```

## 5.3 Explicitly unsupported model fields

The following were tested against PandaScore Series and rejected by the provider:

```text
filter[tournament_id]
filter[team_id]
filter[opponent_id]
```

Therefore they must not be exposed by `series.search`.

In particular, an earlier design such as:

```text
team_id → filter[opponent_id]
```

for Series is incorrect.

## 5.4 Verified semantics

`league_id + year` is not unique.

A League may have multiple Series in the same year, such as qualifiers and the main event.

Therefore:

```text
league_id + year
```

is useful scoping, not guaranteed identity.

`name` is discovery-oriented.

`season` is treated as a structural filter:

```text
season → filter[season]
```

rather than free-text search.

`tier` filtering works server-side.

Provider responses may still contain:

```text
tier = null
```

even when `filter[tier]` was effective, so tests must not assume response tier always echoes the filter.

## 5.5 Frozen navigation boundary

PandaScore Series contains:

```text
tournaments[]
```

This is removed from the DotaMind Series result.

Navigation is explicit:

```text
Series
→ tournament.search(series_id=...)
```

Participating Teams use the explicit relationship operation:

```text
Series
→ series.teams(series_id=...)
```

---

# 6. Series → Teams Relationship

## 6.1 Operation

```text
esports.series.teams
```

This is a relationship/traversal operation, not a Team entity-search overload.

## 6.2 Model-facing contract

```text
series_id: required
team_id?
page=1
limit=20
```

## 6.3 Provider mapping

```text
series_id
→ /dota2/series/{series_id}/teams

team_id
→ filter[id]

page
→ page

limit
→ per_page
```

## 6.4 Relationship semantics

The endpoint establishes:

> Team participated in this Series.

For example:

```text
series.teams(
    series_id=<series>,
    team_id=<team>
)
```

returning a non-empty result proves Series-level Team participation.

## 6.5 Critical temporal finding

The nested PandaScore:

```text
Team.players[]
```

returned by this endpoint is **not** the historical Series roster.

Testing TI 2021 Team Spirit showed that the endpoint returned the same current Team players as the modern Team endpoint.

Therefore:

```text
Series → Team
```

is a historical participation relationship.

But:

```text
Series Team.players[]
```

is a current Team snapshot and must not be interpreted as historical membership.

DotaMind should not expose those nested players through `series.teams`.

The relationship result should be a bounded Team representation. Exact `TeamSummaryDTO` fields remain part of the detailed Team/DTO design.

---

# 7. Tournament Domain

## 7.1 Model-facing contract

```text
esports.tournament.search

id?
series_id?
name?
page=1
limit=20
```

## 7.2 Provider mapping

```text
id
→ filter[id]

series_id
→ filter[serie_id]

name
→ search[name]

page
→ page

limit
→ per_page
```

## 7.3 Verified semantics

Series scoping works correctly.

Incorrect combinations such as:

```text
filter[serie_id]=wrong_series
+
filter[id]=tournament_from_other_series
```

return:

```json
[]
```

Generic stage names such as:

```text
Group Stage
Playoffs
```

are globally ambiguous.

Therefore the preferred discovery pattern is:

```text
known series_id
+
name
```

rather than global name search.

Both:

```text
filter[name]=Group Stage
search[name]=Group Stage
```

worked in the tested Series, but DotaMind retains:

```text
name → search[name]
```

because the model-facing semantic is entity discovery.

---

# 8. Tournament Response Boundary

PandaScore Tournament responses can be very large even when:

```text
per_page=1
```

because each Tournament embeds matches, participating teams, and roster data.

These nested relations have different domain meanings and must not be treated uniformly.

## 8.1 `matches[]`

```text
Tournament.matches[]
```

is a navigation-only child collection.

It is removed before Artifact.

Navigation is:

```text
Tournament
→ match.search(tournament_id=...)
```

---

## 8.2 `teams[]`

```text
Tournament.teams[]
```

represents:

> Teams participating in this Tournament/stage.

This is not equivalent to Series-wide participation.

For example:

```text
Series participants = 16 teams
Playoffs participants = 8 teams
```

Removing this relationship would lose a useful Tournament-level fact and force expensive Match aggregation.

Therefore Tournament-level Team participation is retained as a bounded Team relation.

Exact summary fields remain part of detailed DTO design.

---

## 8.3 `expected_roster[]`

Testing TI 2021 Playoffs (`tournament_id=6868`) showed Team Spirit's roster contained historical/contextual players including:

```text
TORONTOTOKYO
Yatoro
Collapse
Mira
Miposhka
...
```

rather than Team Spirit's current roster.

Therefore:

> `Tournament.expected_roster[]` represents Tournament-context roster membership and provides useful historical roster capability.

This relationship is retained.

Important qualification:

The **membership relation** is historical/contextual, but arbitrary Player attributes embedded inside the roster must not automatically be interpreted as historical snapshots.

For example, fields such as:

```text
active
modified_at
age
image_url
```

may reflect later/current Player entity information.

Therefore DotaMind may safely infer:

> Player X is recorded in Team Y's Tournament roster.

It must not automatically infer:

> every embedded Player property reflects that historical Tournament date.

The precise roster DTO fields remain subject to the detailed DTO discussion.

---

# 9. Match Domain

## 9.1 Model-facing contract

```text
esports.match.search

id?
league_id?
series_id?
tournament_id?
team_id?
winner_id?
name?
status?
lifecycle?
sort?
page=1
limit=20
```

Supported lifecycle:

```text
past
running
upcoming
```

Supported sort:

```text
begin_at_asc
begin_at_desc
```

## 9.2 Provider mapping

```text
id
→ filter[id]

league_id
→ filter[league_id]

series_id
→ filter[serie_id]

tournament_id
→ filter[tournament_id]

team_id
→ filter[opponent_id]

winner_id
→ filter[winner_id]

name
→ search[name]

status
→ filter[status]

begin_at_asc
→ sort=begin_at

begin_at_desc
→ sort=-begin_at

page
→ page

limit
→ per_page
```

Lifecycle selects the endpoint:

```text
None
→ /dota2/matches

past
→ /dota2/matches/past

running
→ /dota2/matches/running

upcoming
→ /dota2/matches/upcoming
```

---

# 10. Match Scope Semantics

The following were verified:

```text
filter[id]
filter[league_id]
filter[serie_id]
filter[tournament_id]
```

All work correctly.

Parent-child scope combinations use AND semantics.

Example:

```text
serie_id=TI2026
+
tournament_id=Playoffs
```

returns only Matches in the Playoffs of that Series.

Incorrect Series/Tournament combinations return an empty set.

---

# 11. Match Team Filter Semantics

PandaScore uses:

```text
filter[opponent_id]
```

to mean:

> matches involving this Team.

DotaMind intentionally exposes the clearer semantic field:

```text
team_id
```

Therefore:

```text
team_id
→ filter[opponent_id]
```

Example:

```text
match.search(
    series_id=10828,
    team_id=1669
)
```

means:

> Matches in TI 2026 involving Team Spirit.

---

## 11.1 Multiple opponent IDs are OR, not intersection

Verified:

```text
filter[opponent_id]=A,B
```

returns Matches involving:

```text
A OR B
```

It does **not** mean:

```text
A vs B
```

Therefore DotaMind must not expose a misleading:

```text
team_id + opponent_id
```

contract that implies a two-Team matchup intersection.

`opponent_id` is removed from the model-facing Match schema.

A true two-Team intersection is currently not a native Match tool capability.

If needed, the model can query one Team within an appropriate scope and inspect the returned Match opponents.

---

# 12. Match Winner Filter

Verified:

```text
winner_id
→ filter[winner_id]
```

and it combines with Series/Tournament scope using AND semantics.

Therefore:

```text
team_id
→ Team participated in the Match

winner_id
→ Team won the Match
```

These are distinct model-facing semantics.

`winner_type` is not part of the current model input contract.

---

# 13. `/past` Is Not `finished`

This distinction is frozen.

Verified:

```text
/dota2/matches/past
```

includes canceled Matches.

For the tested Group Stage:

```text
/past
→ 40 matches
```

including a canceled Match.

While:

```text
/past?filter[status]=finished
→ 39 matches
```

excluded the canceled Match.

Therefore:

```text
lifecycle=past
```

must only select the `/past` endpoint.

It must **not** implicitly add:

```text
filter[status]=finished
```

Only an explicitly supplied:

```text
status=finished
```

may request that restriction.

---

# 14. Match Exact-ID Lookup

Direct access to:

```text
/dota2/matches/1638249
```

returned HTTP 404 during testing.

The successful exact Match lookup is:

```text
/dota2/matches?filter[id]=1638249
```

Therefore the Adapter must not automatically rewrite an exact Match ID into a `/matches/{id}` path.

This should be covered by regression tests.

---

# 15. Match Name Search

```text
search[name]
```

is fuzzy/discovery-oriented.

For example:

```text
Grand final
```

matches many unrelated tournaments globally.

Preferred pattern:

```text
tournament_id
+
name
```

or exact:

```text
id
```

once identity is resolved.

---

# 16. Match Response Boundary

Several nested relations are intrinsic to a Match and are therefore retained conceptually:

```text
opponents[]
results[]
games[]
winner
```

They directly describe:

- who participated;
- the score;
- who won;
- the bounded set of Games composing the Match.

Exact DTO field shapes remain part of detailed Match DTO design.

The following are explicitly outside the DotaMind Match contract and should be removed during response projection:

```text
live
streams_list
detailed_stats
game_advantage
```

Reasons:

### `live` / `streams_list`

Watching locations and PandaScore live-feed capability are outside the application's responsibility.

Match runtime state is already expressed by:

```text
status
```

`live.supported` is a provider capability flag, not Match lifecycle state.

### `detailed_stats`

PandaScore Match detail is not part of the intended free-data path.

Future detailed game analysis will be implemented separately using OpenDota-backed `game_detail`.

### `game_advantage`

The field has unclear product semantics and was observed as `null` across many tested Matches.

It is not admitted into the DotaMind domain without a clear, verified use case.

Complete parent objects such as:

```text
league {}
serie {}
tournament {}
```

are navigation duplication rather than Match intrinsic facts and should not be relied upon as part of the Match contract.

Parent IDs remain the stable navigation mechanism.

---

# 17. Team Domain

## 17.1 Model-facing contract

```text
esports.team.search

id?
name?
acronym?
page=1
limit=20
```

## 17.2 Provider mapping

```text
id
→ filter[id]

name
→ search[name]

acronym
→ search[acronym]

page
→ page

limit
→ per_page
```

## 17.3 Verified semantics

`filter[id]` is exact identity.

`search[name]` is fuzzy discovery.

For example:

```text
Spirit
```

returned multiple Teams.

`search[acronym]` is also fuzzy and can be even more ambiguous.

For example:

```text
TS
```

returned many acronym candidates, and Team Spirit was not guaranteed to appear first.

Therefore neither:

```text
name
acronym
```

should be treated as exact identity.

---

# 18. Team Players Temporal Semantics

Testing:

```text
/dota2/teams?filter[id]=1669
```

against:

```text
/dota2/series/4012/teams?filter[id]=1669
```

showed the embedded `players[]` payloads were identical.

Therefore:

> `Team.players[]` represents current Team membership snapshot.

It must not be interpreted as:

```text
historical Series roster
historical Tournament roster
historical Match lineup
```

This current-state relation is part of the Team domain semantics.

The final shape of the embedded Player summary remains a DTO-design decision.

---

# 19. Player Domain

## 19.1 Model-facing contract

```text
esports.player.search

id?
team_id?
name?
first_name?
last_name?
active?
page=1
limit=20
```

## 19.2 Provider mapping

```text
id
→ filter[id]

team_id
→ filter[team_id]

active
→ filter[active]

name
→ search[name]

first_name
→ search[first_name]

last_name
→ search[last_name]

page
→ page

limit
→ per_page
```

---

# 20. Player Team Temporal Semantics

Testing with current Team Spirit player Larl and historical Team Spirit player TORONTOTOKYO established:

```text
filter[team_id]=1669
```

returns exactly Team Spirit's current player set.

For example:

```text
team_id=1669
+
id=Larl
→ Larl
```

while:

```text
team_id=1669
+
id=TORONTOTOKYO
→ []
```

Therefore:

> `Player.team_id` filtering represents current Team membership.

It is not historical membership.

---

# 21. `Player.current_team`

Verified:

```text
Larl.current_team
→ Team Spirit

TORONTOTOKYO.current_team
→ Aurora
```

Therefore:

> `Player.current_team` is a current-state relation.

It must not be used to infer historical Team membership.

Historical Tournament roster membership belongs to the Tournament domain.

---

# 22. `Player.active`

TORONTOTOKYO was:

```text
active=true
current_team=Aurora
```

Therefore:

> `active` describes the Player's own current active state.

It does not mean:

- active for a particular Team;
- currently belongs to a queried Team;
- participated in a specific Series/Tournament;
- historical membership.

`active` and Team membership are independent concepts.

---

# 23. Player Search Semantics

Verified:

```text
search[name]
search[first_name]
search[last_name]
```

are fuzzy/discovery searches.

Examples such as:

```text
name=Alex
first_name=Alexander
last_name=ov
```

can produce multiple candidates.

Exact Player identity should ultimately rely on:

```text
filter[id]
```

Multiple Player conditions use AND semantics.

---

# 24. Cross-Domain Temporal Model

The most important relationship semantics are now:

```text
Team.players[]
→ current Team membership

Player.current_team
→ current Team relationship

player.search(team_id=...)
→ current Team membership
```

versus:

```text
Series → Team
→ historical Series-level Team participation
```

versus:

```text
Tournament.expected_roster
→ Tournament-context historical roster membership
```

versus:

```text
Match.opponents
Match.results
Match.games
→ intrinsic facts of that Match
```

These relationships must not be substituted for one another.

---

# 25. Historical Roster Capability

Current capability boundary:

## Series-level

```text
Series → Team participation
```

is available.

Reliable Series-level historical Player roster is **not** available from `series.teams`, because its nested players are current Team data.

## Tournament-level

Historical/contextual roster membership **is** available through:

```text
Tournament.expected_roster[]
```

This should be the preferred source for questions such as:

> Who was recorded on Team Spirit's roster at TI 2021?

Subject to the qualification that nested Player entity attributes are not necessarily historical snapshots.

---

# 26. Explicit Navigation Model

The intended hierarchy is:

```text
League
→ Series
→ Tournament
→ Match
→ Games
```

Examples:

```text
league.search(name="The International")
    ↓
series.search(league_id=4106, year=2026)
    ↓
tournament.search(series_id=10828, name="Group Stage")
    ↓
match.search(tournament_id=21545)
```

Team participation:

```text
Series
→ series.teams(series_id=...)
```

Current Team players:

```text
Team
→ team.search(id=...).players
```

Current Player Team:

```text
Player
→ player.search(id=...).current_team
```

Historical Tournament roster:

```text
Tournament
→ expected_roster
```

---

# 27. Frozen Tool Inventory Covered by This Contract

The contract baseline covers:

```text
esports.league.search
esports.series.search
esports.series.teams
esports.tournament.search
esports.match.search
esports.team.search
esports.player.search
```

Artifact tooling remains separate:

```text
artifact.grep
artifact.read
```

Artifact operates on projected DotaMind results, not raw PandaScore responses.

---

# 28. DTO Design Status

Provider → DotaMind semantic contracts are now considered sufficiently calibrated to begin detailed DTO design.

However, the complete field-level DTO contract is intentionally **not frozen here**.

The following remain for domain-by-domain design discussion:

- exact intrinsic fields retained;
- nullability;
- naming normalization;
- summary DTO field sets;
- whether certain presentation fields survive;
- entity vs relation DTO reuse;
- embedded summary depth;
- date/time representation;
- enum/value-object design;
- whether some currently retained provider facts provide enough product value;
- validation rules and Pydantic model structure.

The DTO review should proceed one Domain at a time and should not reopen already verified PandaScore query semantics unless new provider evidence appears.

Recommended order:

```text
League DTO
→ Series DTO
→ Tournament DTO
→ Match DTO
→ Team DTO
→ Player DTO
```

Shared summary/value objects should be finalized only when the relevant domains provide enough evidence to define them cleanly.

---

# 29. Baseline Rule Going Forward

For subsequent DTO design:

> Start from the DotaMind product meaning of the entity, not from the size or shape of the PandaScore response.

A provider field should survive only when it represents a stable DotaMind domain fact or a deliberately retained bounded relation.

A nested object should not survive merely because PandaScore returns it.

A useful historical/current relationship should not be deleted merely because it is nested.

The Provider Boundary answers:

> How do we ask PandaScore?

The Domain Boundary answers:

> What does this information mean to DotaMind?

The Context Boundary answers:

> How much of the resulting DotaMind information should the model see at once?

These responsibilities should remain separate.

后续 DTO 讨论可以直接从 **League DTO** 开始；上面这份基线里涉及 DTO 的内容只作为边界约束，不把具体字段集合视为最终设计。
