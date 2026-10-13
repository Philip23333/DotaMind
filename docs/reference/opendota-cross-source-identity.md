# PandaScore–OpenDota cross-source game identity observations

## Status and evidence boundary

This is a reference of selected source facts observed on 2026-10-13. It records
why a future resolver must keep PandaScore Match/Game identity separate from
OpenDota League/match fields. It is not an implemented mapper, a fixture suite,
or an accuracy claim. The raw responses were inspected locally; this document
preserves the identifiers and field excerpts needed to revisit the examples
without relying on temporary local file paths or copying complete responses.

The PandaScore collection query used for the sampled matches was
`GET /dota2/matches?filter[serie_id]=<pandascore_series_id>&page=<n>&per_page=100`.
PandaScore also documents listing games for a Match at
[`GET /dota2/matches/{match_id}/games`](https://developers.pandascore.co/reference/get_dota2_matches_matchidorslug_games);
that endpoint currently requires a historical or real-time data plan. The
general Dota 2 Match collection is documented at
[`GET /dota2/matches`](https://developers.pandascore.co/reference/get_dota2_matches).

OpenDota candidate rows were read from
`GET /leagues/{league_id}/matches`; selected details were re-read from
`GET /matches/{match_id}`. The [OpenDota API documentation](https://docs.opendota.com/)
describes the League match collection as excluding amateur leagues and
documents `match_id`, `duration`, `start_time`, team IDs/names, `leagueid`, and
`series_id` in its rows. These endpoints and response coverage must be checked
again before implementation; the captured observations below are not live
availability guarantees.

## Identity terms

| Field or object | Meaning in these observations |
|---|---|
| PandaScore Match | One fixture, identified here by its PandaScore Match `id`; its `games[]` contain individual game records. |
| PandaScore Game | One game within a Match, identified by its PandaScore Game `id` and position. |
| OpenDota `match_id` | The Valve single-game ID used by DotaMind as `valve_game_id` for `game.detail`. |
| PandaScore Series ID | A PandaScore competition-stage ID. It does not equal OpenDota `series_id`. |
| OpenDota `leagueid` | OpenDota's league grouping. A League can cover multiple PandaScore Series or tournament scopes. |
| OpenDota `series_id` | A source field grouping OpenDota games; it can vary across games in one PandaScore Match and can be null or zero. |

The cross-source association is an inference from collected facts. PandaScore
does not supply a native Valve game ID in these records. IDs must not be
converted numerically or matched by similar names alone.

## Match and game counterexamples

### BLAST VIII Grand Final: one PandaScore Match, two OpenDota series IDs

PandaScore Match `1709131` (PandaScore Series `11012`) was Team Yandex versus
Team Spirit. Its four games mapped in the sampled comparison as follows:

| Game position | PandaScore Game `id` | OpenDota `match_id` / `valve_game_id` | OpenDota `series_id` | Start-time delta; duration |
|---:|---:|---:|---:|---|
| 1 | `739823` | `9040114168` | `1153411` | -47 s; equal |
| 2 | `739824` | `9040268873` | `1153411` | -37 s; equal |
| 3 | `739825` | `9040460429` | `1153411` | +376 s; equal |
| 4 | `739826` | `9040578015` | `1153562` | -87 s; equal |

The team names, game winners, and durations were consistent in the re-read
details; the fourth game also had the teams on opposite Radiant/Dire sides.
OpenDota League `19102` supplied the candidate rows. The differing fourth-game
`series_id` is a source fact, not evidence that the fourth game belongs to a
different PandaScore Match. Recheck the PandaScore Series `11012` Match record
and each Game, then the four OpenDota match details listed above.

### Yakult Brothers: in-game Team ID changes while the five-account roster agrees

PandaScore Match `1745472` (Upper Bracket Quarterfinal 2, Yakult Brothers vs
Zenith) contains games `740347`, `740348`, and `740349`. The sampled OpenDota
matches are `9042629988`, `9042668580`, and `9042709331` in League `20359`.
OpenDota reports the Yakult-side `dire_team_id` as `10208034` for game 1 and
`9351740` for games 2 and 3. The raw `players[]` account IDs on that side form
the same five-account set in all three details, while PandaScore identifies the
participant as Yakult Brothers throughout. This supports a roster-based
association for the sample; it does not establish a permanent Team-ID mapping.
Recheck PandaScore Match `1745472` and the three OpenDota details above,
comparing exact `account_id` sets by side and allowing side changes.

### old blood vs White Sails: missing second-game Team fields

PandaScore Match `1743558` contains Game `740235` and Game `740236`. Their
sampled OpenDota details are `9041695822` and `9041812996` in League `20359`.
In game 1, OpenDota reports Old blood as Radiant (`radiant_team_id=10293541`)
and White Sails as Dire (`dire_team_id=10232798`). In the game-2 League-list
response, `dire_team_id` and `dire_team_name` are explicitly `null`, and
`series_id` is `0`. In the game-2 single-game detail response, `dire_team_id`
and `dire_team` are omitted (there is no `dire_name` field), and `series_id` is
also `0`. The five exact player `account_id` values on Old
blood's side in game 1 recur on the Dire side in game 2; White Sails' five
accounts also recur on the opposite side. Team identity for the missing side is
therefore an account-roster inference, not an explicit game-2 Team field.
Recheck both OpenDota details and the PandaScore Match/Game participants; do not
fill the missing Team ID in the stored source response.

### New Growth vs Pizza Hook: contradictory PandaScore time fields

PandaScore Match `1744284`, Game `740340` (position 3), records
`begin_at=2026-10-13T02:31:22Z`, `end_at=2026-10-13T02:31:25Z`, and
`length=1907` seconds. Its parent Match ends at `2026-10-13T02:31:24Z`.
OpenDota League `20359` had no candidate under the initial time window. A
bounded wider comparison found OpenDota match `9042461131`, whose start is
10,258 seconds earlier and whose duration is also 1,907 seconds. Its teams,
winner, and neighboring-game context agreed with the PandaScore sample. This is
a context-supported cross-source inference after widening, not a general rule
that duration equality is sufficient. Recheck the PandaScore Series `11105`
Match/Game record and OpenDota League `20359` list/detail for
`9042461131`; preserve the contradictory source times.

## OpenDota `series_id` variation in the sampled multi-game set

The following five PandaScore Matches had more than one distinct positive
OpenDota `series_id` across their games:

| PandaScore Match | Games and corresponding OpenDota `match_id` values | Observed OpenDota `series_id` values |
|---|---|---|
| BLAST VIII Grand Final `1709131` | `739823`→`9040114168`; `739824`→`9040268873`; `739825`→`9040460429`; `739826`→`9040578015` | `1153411` for games 1–3; `1153562` for game 4 |
| DreamLeague China Closed Qualifier, YB vs Zenith `1745472` | `740347`→`9042629988`; `740348`→`9042668580`; `740349`→`9042709331` | `1154058` for game 1; `1154073` for games 2–3 |
| PGL Wallachia S9, PIPS+4 vs YB `1694718` | `739484`→`9008125103`; `739485`→`9008292090`; `739486`→`9008436237` | `1144631` for games 1–2; `1144747` for game 3 |
| BLAST VII semifinal, Liquid vs AUR `1501581` | `736452`→`8831817474`; `736453`→`8831927547` | `1104229`; `1104277` |
| BLAST VII quarterfinal, TS vs OG `1501578` | `736443`→`8831470213`; `736444`→`8831571711` | `1104064`; `1104122` |

Five further multi-game Matches had a null/zero `series_id` on at least one
game while another game had a positive value:

| PandaScore Match | Games and corresponding OpenDota `match_id` values | Observed OpenDota `series_id` values |
|---|---|---|
| BLAST VIII decider, GL vs Liquid `1709095` | `739781`→`9026055399`; `739782`→`9026176585` | null; `1149441` |
| BLAST VIII, AUR vs GL `1709092` | `739772`→`9021939258`; `739773`→`9022024252` | null; `1148468` |
| TI 2026, IW vs TS `1638165` | `738754`→`8955197224`; `738755`→`8955247801` | null; `1132142` |
| old blood vs White Sails `1743558` | `740235`→`9041695822`; `740236`→`9041812996` | `1153816`; zero |
| PGL Wallachia S9, Nem vs GL `1694732` | `739526`→`9010695250`; `739527`→`9010744805`; `739528`→`9010797995` | null for game 1; `1145355` for games 2–3 |

### Sample counts and limits

The 2026-10-13 comparison considered 165 selected PandaScore Matches with at
least two finished, non-forfeit games. 157 had complete one-to-one candidate
correspondence for the included games; eight TI Matches were excluded because
the set could not be completely paired. Within those 157, five Matches had
multiple distinct positive `series_id` values and five different Matches had
at least one null/zero value. These groups did not overlap: 10/157 (6.37%) had
one of the two observed patterns. Excluding the BLAST VIII Grand Final, 4/156
(2.56%) had multiple positive values. These are counts from selected
competitions, not a random OpenDota or PandaScore population sample.

The candidate study selected leagues manually by competition/season and used
start-time and duration filters to build candidates; the filters were not an
identity acceptance rule. A unique time/duration candidate was not treated as
proof. Twenty-five anomalous match details were re-read and their `series_id`
agreed with their corresponding list row. This check verifies those sampled
rows, not the correctness of an automatic resolver.

The sampled OpenDota League list had null team-name fields for matches where
the detail endpoint supplied names for most checked games. League `20359` also
covered multiple DreamLeague regions/rounds; League `19944` appeared across
multiple EPL Masters editions. Therefore League membership alone does not
establish one PandaScore Series or Tournament, and a missing list name may
require a bounded detail read rather than a fabricated label.

## What these observations establish

- OpenDota `series_id` is useful source context but cannot be a mandatory
  same-Match identity key.
- Null, zero, or changing in-game Team IDs must be preserved as source facts;
  exact player-account evidence can support a separately labeled inference.
- Candidate list rows can be incomplete, and source time fields can conflict.
- A correctly paired candidate still needs evidence beyond list ordering or one
  matching field.

They do **not** establish all-provider coverage, a global Team/player identity
map, a match-resolution algorithm, resolver accuracy, or current endpoint
availability. The planned matching contract and future acceptance are owned by
[`../DATA.md`](../DATA.md) and [`../EVALS.md`](../EVALS.md).
