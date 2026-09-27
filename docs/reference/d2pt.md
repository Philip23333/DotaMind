# D2PT guide source reference

## Evidence scope

This page records source facts observed from one Sven (`hero_id=18`) request to
each endpoint on 2026-09-27. It is a reference for future contract and parser
work, not an implementation status log. The tested WSL Ubuntu environment used
Python 3.14.4 and `urllib.request.urlopen`, with a 30-second timeout and one
request per endpoint. The request headers were:

```text
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
            (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36
Referer: https://dota2protracker.com/
Accept: application/json
```

No API key, Cookie, or Authorization header was sent. No proxy was explicitly
configured; the post-request Python proxy-discovery mapping was empty. These
results verify access and the sampled response shapes in that environment only.
They do not establish a production integration, full hero/position coverage,
long-term availability, a persistent cache, or scheduled refresh.

The endpoint paths follow the [D2PT Guides request implementation](https://github.com/Darktex/d2pt-guides/blob/main/d2pt_guides/d2pt.py):

| Source sample | Request |
|---|---|
| Pub build statistics | `GET https://dota2protracker.com/api/hero/18/builds?position=pos%201` |
| Pro build statistics | `GET https://dota2protracker.com/api/hero/18/pro-builds` |

## Observed response overview

| Sample | HTTP | Root | Rows | Bytes | Elapsed | Source update field |
|---|---:|---|---:|---:|---:|---|
| Pub, hero 18, pos 1 | 200 | array | 1 | 43,825 | 1,093.4 ms | `2026-09-27 08:06:25` |
| Pro, hero 18, pos 1 | 200 | array | 1 | 75,377 | 1,140.6 ms | `2026-09-27T14:29:17` |

Both rows had `hero_id=18` and `position="pos 1"`. Each row is an aggregate
build record, not one match. HTTP response `Date` was `2026-09-27 16:13:42 GMT`
for Pub and `2026-09-27 16:13:44 GMT` for Pro. `Last-Modified` was
`2026-09-27 16:02:44 GMT` and `2026-09-27 16:02:48 GMT`, respectively. These
HTTP values are resource/response metadata and do not prove when source
statistics were updated. The `updated_at` strings have no explicit timezone in
the payload.

## Pub response shape

The root is an array containing one object. Root fields observed:

```text
build_data, build_id, data_scope, facet_id, hero_id, num_matches, num_wins,
pick_rate, position, source, updated_at
```

The sample had `source="pubs"`, `facet_id=0`, `build_id=0`,
`num_matches=10390`, `num_wins=5385`, and root `pick_rate=100.0`. `data_scope`
contained `configured_window_days=14`, `patch_versions=["7.41f"]`, and
`analysis_start_ts`, `analysis_end_ts`, `first_match_ts`, and `last_match_ts`.
This identifies the declared window and patch label for this row; it does not
establish every filter or the denominator for every nested statistic.

The `build_data` object contained these candidate guide fields:

| Field | Observed shape |
|---|---|
| `starting_items` | array, length 46 |
| `starting_items_new` | array, length 3; item-ID sequences and statistics |
| `anchor_build` | array, length 2; one array element and one integer element |
| `anchor_items` | array, length 9 |
| `anchor_items2` | array, length 8 |
| `items_mid_late` | array, length 17 |
| `sixslot` | array, length 34 |
| `abilities` | array, length 10 |
| `abilities_new` | array, length 5; skill-ID sequences and statistics |
| `talents` | array, length 4 |
| `neutral_stats` | object with keys `0` through `4` |

Other observed `build_data` keys included `num_matches`, `num_wins`,
`pick_rate`, `win_rate`, `data_scope`, `anchor_item_stats`,
`anchor_lategame_inventories`, `enhancement_stats`,
`has_anchor_build`, and `starting_inventory_coverage` /
`starting_inventory_options`.

`build_data.win_rate=0.5182868142444659`, exactly equal to
`5385 / 10390`. Counts were non-negative and wins did not exceed matches.
However, root `pick_rate=100.0` and `build_data.pick_rate=1.0`; the response does
not prove their units or conversion relationship.

`pr` is nested and path-dependent. Examples of observed ranges include
`abilities_new` sequence entries `0.042–0.2191`, `anchor_items`
`0.6272–0.9910`, `items_mid_late` `0.00289–0.97815`, `starting_items`
`0–0.77`, and `anchor_item_stats.<id>.pr` `0.0215–100.0215`. Preserve raw
values; the last value is an observed outlier, not a value to normalize by
assumption.

## Pro response shape

The root is an array containing one object. Root fields observed:

```text
abilities, account_ids, build_id, build_label, build_stats, build_type,
core_items, facet_id, hero_id, match_count, match_ids, neutral_items,
num_matches, num_wins, pick_rate, player_count, players, position,
recent_matches, references, source, starting_items, updated_at
```

The sample had `source="hermes_autonomous_refresh"`, `facet_id=0`,
`build_id=1`, `build_type="build"`, `build_label="Standard"`,
`num_matches=80`, `match_count=80`, `num_wins=46`, root `pick_rate=1.0`, and
`player_count=49`. It contained 80 `match_ids` and five `recent_matches`.
The root row identity matched hero 18 / pos 1. Other heroes and positions in
recent match drafts are match context, not a mismatch in the root build row.

Observed guide-relevant shapes:

- `starting_items`: array, length 3.
- `abilities`: object with `skill_order` array length 10 and `talents` array
  length 11.
- `neutral_items`: object with tier keys `1` through `5`.
- `core_items`: object with `build_order` and `top_items`.
- The Pub-specific candidate fields `starting_items_new`, `anchor_build`,
  `anchor_items`, `anchor_items2`, `items_mid_late`, `sixslot`, `abilities_new`,
  and `neutral_stats` were absent.

The aggregate ratio is `46 / 80 = 0.575`; counts were non-negative and wins did
not exceed matches. The root record had no `win_rate` field. No `pr` field was
observed. Nested `pick_rate` examples varied by path: skill choices
`0.0125–1.0`, talent choices `0.1026–1.0`, core build order `0.35–1.0`, core
top items `0.05–1.0`, starting items `0.1125–0.225`, and neutral items
`0.0125–0.5`. Do not assume these paths share a unit or denominator.

`players[].team_id`, `team_name`, `team_tag`, and `team_logo` included both null
and non-null values. Preserve those source variations rather than forcing one
type. Pro aggregate statistics are not a substitute for the individual
`recent_matches` examples when the product needs concrete professional-play
references.

## Time, versions, and statistic limits

The Pub `data_scope` exposed a 14-day configured window, patch label `7.41f`, and
four Unix timestamp boundaries. The Pro sample exposed counts, match IDs,
players, and five recent matches, but no `data_scope`, patch/version, or full
statistics window. `source`, endpoint names, `build_label`, and `updated_at` do
not establish the rules that selected matches for either aggregate.

`avg_minute` appeared in multiple nested item paths. Observed Pub ranges were
`5.459–27.965` for `anchor_items`, `14.062–54.4` for `items_mid_late`, and
`1.7–54.7` for `anchor_item_stats`. Pro ranges included `2.43–60` for
`core_items.top_items`, `5.51–38.96` for `core_items.build_order`, and `5–63`
for `neutral_items`. `std_minute` appeared in Pub paths (`1.297–5.160` for
`anchor_items`, `1.760–10.557` for `items_mid_late`, and `0–13.4` for
`anchor_item_stats`) and was absent in the Pro sample. These field names and
values do not prove a universal calculation method or time unit.

The sample also contained heterogeneous nested values: Pub
`abilities_new[][]` included both arrays and objects, `anchor_build` mixed an
array and integer, and `abilities[].slot` was null. The single root row per
endpoint cannot establish cross-row schema variation, duplicate-ID behavior,
all-hero coverage, or long-term stability.

## Use and interpretation boundary

Verified: the tested requests were accessible in the stated environment; both
returned non-empty JSON; and the individual sample structures and count ratios
above were inspected. Still unconfirmed: source selection rules, all nested
statistic units and denominators, the causal effect of an item, exact
`avg_minute` / `std_minute` methodology, and universal freshness semantics.
Do not describe Pub endpoint data as professional matches or infer that an
empty Pro result means the hero has no professional games. Do not treat
`retrieved_at` or HTTP `Last-Modified` as the source statistics update time.
These two Sven records do not demonstrate complete hero coverage or production
availability.

## Offline fixtures and separate environment evidence

The raw WSL response bodies are preserved byte-for-byte for offline contract
tests:

- [Pub Sven pos 1 fixture](../../apps/api/tests/vnext/fixtures/d2pt/pub_sven_pos1.json)
- [Pro Sven fixture](../../apps/api/tests/vnext/fixtures/d2pt/pro_sven.json)
- [Fixture provenance, sizes, and SHA-256](../../apps/api/tests/vnext/fixtures/d2pt/README.md)

A separate user-provided report states that D2PT connectivity succeeded from a
Guangzhou container. That report is independent of these WSL-sourced fixture
files; the fixtures were not retrieved from the container. Neither result
establishes full hero/position coverage, a persistent cache, or scheduled
refresh.
