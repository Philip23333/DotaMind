# get_dota2_tournaments_upcoming

Official PandaScore reference extracted from the page’s OpenAPI definition. This file preserves endpoint-local parameter and response semantics; it does not unify them with other endpoints.

## Identity

- **Title:** Get upcoming Dota 2 tournaments
- **Method:** GET
- **API path:** `/dota2/tournaments/upcoming`
- **Requested path:** `/dota2/tournaments/upcoming`
- **Reference URL:** https://developers.pandascore.co/reference/get_dota2_tournaments_upcoming.md
- **Availability:** Yes — page text explicitly says “available to all customers”.

## Description

List upcoming Dota 2 tournaments
> ℹ️  
> 
> This endpoint is available to all customers

## Path Parameters

None documented.

## Query Parameters

### filter

| field | type | description | constraints |
| --- | --- | --- | --- |
| begin_at | array<string; format: date-time> | — | minItems=1 |
| country | array<string> | — | minItems=1 |
| detailed_stats | boolean | Whether the tournament is expected to have detailed statistics available | — |
| end_at | array<string; format: date-time> | — | minItems=1 |
| has_bracket | boolean | Whether the tournament has a bracket | — |
| id | array<integer> | — | minItems=1 |
| live_supported | boolean | Whether live is supported | — |
| modified_at | array<string; format: date-time> | — | minItems=1 |
| name | array<string> | — | minItems=1 |
| prizepool | array<string> | — | minItems=1 |
| region | array<string; enum: AF, ASIA, EEU, ME, NA, OCE, SA, WEU> | — | minItems=1 |
| serie_id | array<integer> | — | minItems=1 |
| slug | array<string> | — | minItems=1 |
| tier | array<string; enum: a, b, c, d, s, unranked> | — | minItems=1 |
| videogame_title | array<one of: integer, string> | A videogame title id or slug. Only for `/csgo/*`, `/codmw/*`, `/fifa/*` and `/ow/*` endpoints | minItems=1 |
| winner_id | array<unknown> | — | minItems=1 |
| winner_type | array<string; enum: Player, Team> | — | minItems=1 |

### search

| field | type | description | constraints |
| --- | --- | --- | --- |
| country | string | Country code matching the location of the tournament according to the ISO 3166-1 standard (Alpha-2 code). In addition to the standard, the XK code is used for Kosovo. null if unknown | — |
| name | string | — | — |
| prizepool | string | — | — |
| region | string; enum: AF, ASIA, EEU, ME, NA, OCE, SA, WEU | Region acronym for the location of the tournament. | — |
| slug | string | — | minLength=1; pattern=^[a-z0-9_-]+$ |
| tier | string; enum: a, b, c, d, s, unranked | The tier of the tournament, ranging from 'S' to 'Unranked'. Ranking 'S' > 'A' > 'B' > 'C' > 'D' > 'Unranked' | — |
| winner_type | string; enum: Player, Team | — | — |

### range

| field | type | description | constraints |
| --- | --- | --- | --- |
| begin_at | array<string; format: date-time> | — | minItems=2; maxItems=2 |
| country | array<string> | — | minItems=2; maxItems=2 |
| detailed_stats | array<boolean> | — | minItems=2; maxItems=2 |
| end_at | array<string; format: date-time> | — | minItems=2; maxItems=2 |
| has_bracket | array<boolean> | — | minItems=2; maxItems=2 |
| id | array<integer> | — | minItems=2; maxItems=2 |
| modified_at | array<string; format: date-time> | — | minItems=2; maxItems=2 |
| name | array<string> | — | minItems=2; maxItems=2 |
| prizepool | array<string> | — | minItems=2; maxItems=2 |
| region | array<string; enum: AF, ASIA, EEU, ME, NA, OCE, SA, WEU> | — | minItems=2; maxItems=2 |
| serie_id | array<integer> | — | minItems=2; maxItems=2 |
| slug | array<string> | — | minItems=2; maxItems=2 |
| tier | array<string; enum: a, b, c, d, s, unranked> | — | minItems=2; maxItems=2 |
| winner_id | array<unknown> | — | minItems=2; maxItems=2 |
| winner_type | array<string; enum: Player, Team> | — | minItems=2; maxItems=2 |

### sort

| field | ascending syntax | descending syntax | notes |
| --- | --- | --- | --- |
| begin_at | begin_at | -begin_at | Use `-` prefix for descending order. |
| country | country | -country | Use `-` prefix for descending order. |
| detailed_stats | detailed_stats | -detailed_stats | Use `-` prefix for descending order. |
| end_at | end_at | -end_at | Use `-` prefix for descending order. |
| has_bracket | has_bracket | -has_bracket | Use `-` prefix for descending order. |
| id | id | -id | Use `-` prefix for descending order. |
| modified_at | modified_at | -modified_at | Use `-` prefix for descending order. |
| name | name | -name | Use `-` prefix for descending order. |
| prizepool | prizepool | -prizepool | Use `-` prefix for descending order. |
| region | region | -region | Use `-` prefix for descending order. |
| serie_id | serie_id | -serie_id | Use `-` prefix for descending order. |
| slug | slug | -slug | Use `-` prefix for descending order. |
| tier | tier | -tier | Use `-` prefix for descending order. |
| winner_id | winner_id | -winner_id | Use `-` prefix for descending order. |
| winner_type | winner_type | -winner_type | Use `-` prefix for descending order. |

### pagination

| parameter | type | default | constraints | description |
| --- | --- | --- | --- | --- |
| page | one of: integer, object | — | — | Pagination in the form of `page=2` or `page[size]=30&page[number]=2` |
| per_page | integer | 50 | minimum=1; maximum=100; default=50 | Equivalent to `page[size]` |

### other query parameters

None documented.

## Request Example

Official curl example:

```curl
curl --request GET \
     --url 'https://api.pandascore.co/dota2/tournaments/upcoming' \
     --header 'accept: application/json'

```

## 200 Response Example

A list of Dota2 tournaments

```json
[
  {
    "begin_at": "2025-10-10T03:00:00Z",
    "country": null,
    "detailed_stats": true,
    "end_at": "2025-10-12T10:00:00Z",
    "expected_roster": [
      {
        "players": [],
        "team": {
          "acronym": "XctN",
          "dark_mode_image_url": null,
          "id": 1660,
          "image_url": "https://cdn.pandascore.co/images/team/image/1660/771px_execration_2024_full_allmode.png",
          "location": "PH",
          "modified_at": "2025-10-02T08:22:47Z",
          "name": "Execration",
          "slug": "execration"
        }
      },
      {
        "players": [],
        "team": {
          "acronym": "BOOM",
          "dark_mode_image_url": null,
          "id": 126229,
          "image_url": "https://cdn.pandascore.co/images/team/image/126229/boom-esports.png",
          "location": "ID",
          "modified_at": "2025-10-02T08:22:49Z",
          "name": "BOOM Esports",
          "slug": "boom-esports"
        }
      },
      {
        "players": [],
        "team": {
          "acronym": "TLN",
          "dark_mode_image_url": null,
          "id": 129862,
          "image_url": "https://cdn.pandascore.co/images/team/image/129862/900px_talon_esports_logo_2021.png",
          "location": "HK",
          "modified_at": "2025-09-26T21:07:51Z",
          "name": "Talon Esports",
          "slug": "talon-esports-dota-2"
        }
      },
      {
        "players": [],
        "team": {
          "acronym": "Nem",
          "dark_mode_image_url": "https://cdn.pandascore.co/dark_images/team/dark_image/136650/285px_team_nem_darkmode.png",
          "id": 136650,
          "image_url": "https://cdn.pandascore.co/images/team/image/136650/159px_team_nem_lightmode.png",
          "location": "PH",
          "modified_at": "2025-10-02T05:08:02Z",
          "name": "Team Nemesis",
          "slug": "team-nemesis"
        }
      }
    ],
    "has_bracket": true,
    "id": 17746,
    "league": {
      "id": 5319,
      "image_url": null,
      "modified_at": "2024-11-14T08:26:28Z",
      "name": "BLAST Slam",
      "slug": "dota-2-blast-slam",
      "url": null
    },
    "league_id": 5319,
    "live_supported": false,
    "matches": [
      {
        "begin_at": "2025-10-10T03:00:00Z",
        "detailed_stats": true,
        "draw": false,
        "end_at": null,
        "forfeit": false,
        "game_advantage": null,
        "id": 1248985,
        "live": {
          "opens_at": null,
          "supported": false,
          "url": null
        },
        "match_type": "best_of",
        "modified_at": "2025-10-03T16:01:29Z",
        "name": "Upper bracket quarterfinal 1: TBD vs TBD",
        "number_of_games": 3,
        "original_scheduled_at": "2025-10-10T03:00:00Z",
        "rescheduled": false,
        "scheduled_at": "2025-10-10T03:00:00Z",
        "slug": "2025-10-10-d4333581-6ea4-494b-a80d-f4213fd6d982",
        "status": "not_started",
        "streams_list": [
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_d",
            "language": "en",
            "main": false,
            "official": false,
            "raw_url": "https://www.twitch.tv/rlg_dota2_d"
          },
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_b",
            "language": "en",
            "main": true,
            "official": true,
            "raw_url": "https://www.twitch.tv/rlg_dota2_b"
          }
        ],
        "tournament_id": 17746,
        "winner_id": null,
        "winner_type": "Team"
      },
      {
        "begin_at": "2025-10-10T03:00:00Z",
        "detailed_stats": true,
        "draw": false,
        "end_at": null,
        "forfeit": false,
        "game_advantage": null,
        "id": 1248986,
        "live": {
          "opens_at": null,
          "supported": false,
          "url": null
        },
        "match_type": "best_of",
        "modified_at": "2025-10-03T16:01:29Z",
        "name": "Upper bracket quarterfinal 2: TBD vs TBD",
        "number_of_games": 3,
        "original_scheduled_at": "2025-10-10T03:00:00Z",
        "rescheduled": false,
        "scheduled_at": "2025-10-10T03:00:00Z",
        "slug": "2025-10-10-bb1e18c5-d657-48a8-a3c9-23e819c9050d",
        "status": "not_started",
        "streams_list": [
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_d",
            "language": "en",
            "main": false,
            "official": false,
            "raw_url": "https://www.twitch.tv/rlg_dota2_d"
          },
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_b",
            "language": "en",
            "main": true,
            "official": true,
            "raw_url": "https://www.twitch.tv/rlg_dota2_b"
          }
        ],
        "tournament_id": 17746,
        "winner_id": null,
        "winner_type": "Team"
      },
      {
        "begin_at": "2025-10-10T06:00:00Z",
        "detailed_stats": true,
        "draw": false,
        "end_at": null,
        "forfeit": false,
        "game_advantage": null,
        "id": 1248988,
        "live": {
          "opens_at": null,
          "supported": false,
          "url": null
        },
        "match_type": "best_of",
        "modified_at": "2025-10-03T16:01:29Z",
        "name": "Upper bracket quarterfinal 3: TBD vs TBD",
        "number_of_games": 3,
        "original_scheduled_at": "2025-10-10T06:00:00Z",
        "rescheduled": false,
        "scheduled_at": "2025-10-10T06:00:00Z",
        "slug": "2025-10-10-cf767d5b-3eac-4b82-a2b7-1b7287073d36",
        "status": "not_started",
        "streams_list": [
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_d",
            "language": "en",
            "main": false,
            "official": false,
            "raw_url": "https://www.twitch.tv/rlg_dota2_d"
          },
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_b",
            "language": "en",
            "main": true,
            "official": true,
            "raw_url": "https://www.twitch.tv/rlg_dota2_b"
          }
        ],
        "tournament_id": 17746,
        "winner_id": null,
        "winner_type": "Team"
      },
      {
        "begin_at": "2025-10-10T06:00:00Z",
        "detailed_stats": true,
        "draw": false,
        "end_at": null,
        "forfeit": false,
        "game_advantage": null,
        "id": 1248989,
        "live": {
          "opens_at": null,
          "supported": false,
          "url": null
        },
        "match_type": "best_of",
        "modified_at": "2025-10-03T16:01:29Z",
        "name": "Upper bracket quarterfinal 4: TBD vs TBD",
        "number_of_games": 3,
        "original_scheduled_at": "2025-10-10T06:00:00Z",
        "rescheduled": false,
        "scheduled_at": "2025-10-10T06:00:00Z",
        "slug": "2025-10-10-4c684e18-313b-4b12-a292-961e830b973c",
        "status": "not_started",
        "streams_list": [
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_d",
            "language": "en",
            "main": false,
            "official": false,
            "raw_url": "https://www.twitch.tv/rlg_dota2_d"
          },
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_b",
            "language": "en",
            "main": true,
            "official": true,
            "raw_url": "https://www.twitch.tv/rlg_dota2_b"
          }
        ],
        "tournament_id": 17746,
        "winner_id": null,
        "winner_type": "Team"
      },
      {
        "begin_at": "2025-10-10T09:00:00Z",
        "detailed_stats": true,
        "draw": false,
        "end_at": null,
        "forfeit": false,
        "game_advantage": null,
        "id": 1248990,
        "live": {
          "opens_at": null,
          "supported": false,
          "url": null
        },
        "match_type": "best_of",
        "modified_at": "2025-10-03T16:01:29Z",
        "name": "Lower bracket round 1 match 1: TBD vs TBD",
        "number_of_games": 3,
        "original_scheduled_at": "2025-10-10T09:00:00Z",
        "rescheduled": false,
        "scheduled_at": "2025-10-10T09:00:00Z",
        "slug": "2025-10-10-654c448a-0c93-4b3c-bd5c-435a6d360064",
        "status": "not_started",
        "streams_list": [
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_d",
            "language": "en",
            "main": false,
            "official": false,
            "raw_url": "https://www.twitch.tv/rlg_dota2_d"
          },
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_b",
            "language": "en",
            "main": true,
            "official": true,
            "raw_url": "https://www.twitch.tv/rlg_dota2_b"
          }
        ],
        "tournament_id": 17746,
        "winner_id": null,
        "winner_type": "Team"
      },
      {
        "begin_at": "2025-10-10T09:00:00Z",
        "detailed_stats": true,
        "draw": false,
        "end_at": null,
        "forfeit": false,
        "game_advantage": null,
        "id": 1248991,
        "live": {
          "opens_at": null,
          "supported": false,
          "url": null
        },
        "match_type": "best_of",
        "modified_at": "2025-10-03T16:01:29Z",
        "name": "Lower bracket round 1 match 2: TBD vs TBD",
        "number_of_games": 3,
        "original_scheduled_at": "2025-10-10T09:00:00Z",
        "rescheduled": false,
        "scheduled_at": "2025-10-10T09:00:00Z",
        "slug": "2025-10-10-57e6f4ac-e0e0-4352-83fb-9b447e4e7b47",
        "status": "not_started",
        "streams_list": [
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_d",
            "language": "en",
            "main": false,
            "official": false,
            "raw_url": "https://www.twitch.tv/rlg_dota2_d"
          },
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_b",
            "language": "en",
            "main": true,
            "official": true,
            "raw_url": "https://www.twitch.tv/rlg_dota2_b"
          }
        ],
        "tournament_id": 17746,
        "winner_id": null,
        "winner_type": "Team"
      },
      {
        "begin_at": "2025-10-10T12:00:00Z",
        "detailed_stats": true,
        "draw": false,
        "end_at": null,
        "forfeit": false,
        "game_advantage": null,
        "id": 1248992,
        "live": {
          "opens_at": null,
          "supported": false,
          "url": null
        },
        "match_type": "best_of",
        "modified_at": "2025-10-03T16:01:29Z",
        "name": "Upper bracket semifinal 1: TBD vs TBD",
        "number_of_games": 3,
        "original_scheduled_at": "2025-10-10T12:00:00Z",
        "rescheduled": false,
        "scheduled_at": "2025-10-10T12:00:00Z",
        "slug": "2025-10-10-d347be43-94fd-44a4-98c0-4a227f3a8c35",
        "status": "not_started",
        "streams_list": [
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_d",
            "language": "en",
            "main": false,
            "official": false,
            "raw_url": "https://www.twitch.tv/rlg_dota2_d"
          },
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_b",
            "language": "en",
            "main": true,
            "official": true,
            "raw_url": "https://www.twitch.tv/rlg_dota2_b"
          }
        ],
        "tournament_id": 17746,
        "winner_id": null,
        "winner_type": "Team"
      },
      {
        "begin_at": "2025-10-10T12:00:00Z",
        "detailed_stats": true,
        "draw": false,
        "end_at": null,
        "forfeit": false,
        "game_advantage": null,
        "id": 1248994,
        "live": {
          "opens_at": null,
          "supported": false,
          "url": null
        },
        "match_type": "best_of",
        "modified_at": "2025-10-03T16:01:29Z",
        "name": "Upper bracket semifinal 2: TBD vs TBD",
        "number_of_games": 3,
        "original_scheduled_at": "2025-10-10T12:00:00Z",
        "rescheduled": false,
        "scheduled_at": "2025-10-10T12:00:00Z",
        "slug": "2025-10-10-e223cf5c-12a7-4b8e-81a1-78ae1da28b89",
        "status": "not_started",
        "streams_list": [
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_d",
            "language": "en",
            "main": false,
            "official": false,
            "raw_url": "https://www.twitch.tv/rlg_dota2_d"
          },
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_b",
            "language": "en",
            "main": true,
            "official": true,
            "raw_url": "https://www.twitch.tv/rlg_dota2_b"
          }
        ],
        "tournament_id": 17746,
        "winner_id": null,
        "winner_type": "Team"
      },
      {
        "begin_at": "2025-10-11T03:00:00Z",
        "detailed_stats": true,
        "draw": false,
        "end_at": null,
        "forfeit": false,
        "game_advantage": null,
        "id": 1248997,
        "live": {
          "opens_at": null,
          "supported": false,
          "url": null
        },
        "match_type": "best_of",
        "modified_at": "2025-10-03T16:01:29Z",
        "name": "Lower bracket round 2 match 1: TBD vs TBD",
        "number_of_games": 3,
        "original_scheduled_at": "2025-10-11T03:00:00Z",
        "rescheduled": false,
        "scheduled_at": "2025-10-11T03:00:00Z",
        "slug": "2025-10-11-417cf533-7c9f-4830-ab33-2ad75d070322",
        "status": "not_started",
        "streams_list": [
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_d",
            "language": "en",
            "main": false,
            "official": false,
            "raw_url": "https://www.twitch.tv/rlg_dota2_d"
          },
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_b",
            "language": "en",
            "main": true,
            "official": true,
            "raw_url": "https://www.twitch.tv/rlg_dota2_b"
          }
        ],
        "tournament_id": 17746,
        "winner_id": null,
        "winner_type": "Team"
      },
      {
        "begin_at": "2025-10-11T06:00:00Z",
        "detailed_stats": true,
        "draw": false,
        "end_at": null,
        "forfeit": false,
        "game_advantage": null,
        "id": 1248998,
        "live": {
          "opens_at": null,
          "supported": false,
          "url": null
        },
        "match_type": "best_of",
        "modified_at": "2025-10-03T16:01:29Z",
        "name": "Lower bracket round 2 match 2: TBD vs TBD",
        "number_of_games": 3,
        "original_scheduled_at": "2025-10-11T06:00:00Z",
        "rescheduled": false,
        "scheduled_at": "2025-10-11T06:00:00Z",
        "slug": "2025-10-11-5ca76a02-590f-430c-97dc-fa50bf6014a7",
        "status": "not_started",
        "streams_list": [
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_d",
            "language": "en",
            "main": false,
            "official": false,
            "raw_url": "https://www.twitch.tv/rlg_dota2_d"
          },
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_b",
            "language": "en",
            "main": true,
            "official": true,
            "raw_url": "https://www.twitch.tv/rlg_dota2_b"
          }
        ],
        "tournament_id": 17746,
        "winner_id": null,
        "winner_type": "Team"
      },
      {
        "begin_at": "2025-10-11T09:00:00Z",
        "detailed_stats": true,
        "draw": false,
        "end_at": null,
        "forfeit": false,
        "game_advantage": null,
        "id": 1248999,
        "live": {
          "opens_at": null,
          "supported": false,
          "url": null
        },
        "match_type": "best_of",
        "modified_at": "2025-10-03T16:01:29Z",
        "name": "Lower bracket semifinal: TBD vs TBD",
        "number_of_games": 3,
        "original_scheduled_at": "2025-10-11T09:00:00Z",
        "rescheduled": false,
        "scheduled_at": "2025-10-11T09:00:00Z",
        "slug": "2025-10-11-933478f1-1cba-4fb7-811d-cec6128ef780",
        "status": "not_started",
        "streams_list": [
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_d",
            "language": "en",
            "main": false,
            "official": false,
            "raw_url": "https://www.twitch.tv/rlg_dota2_d"
          },
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_b",
            "language": "en",
            "main": true,
            "official": true,
            "raw_url": "https://www.twitch.tv/rlg_dota2_b"
          }
        ],
        "tournament_id": 17746,
        "winner_id": null,
        "winner_type": "Team"
      },
      {
        "begin_at": "2025-10-11T12:00:00Z",
        "detailed_stats": true,
        "draw": false,
        "end_at": null,
        "forfeit": false,
        "game_advantage": null,
        "id": 1249000,
        "live": {
          "opens_at": null,
          "supported": false,
          "url": null
        },
        "match_type": "best_of",
        "modified_at": "2025-10-03T16:01:29Z",
        "name": "Upper bracket final: TBD vs TBD",
        "number_of_games": 3,
        "original_scheduled_at": "2025-10-11T12:00:00Z",
        "rescheduled": false,
        "scheduled_at": "2025-10-11T12:00:00Z",
        "slug": "2025-10-11-8dc1bba0-e2c1-4ee9-9c02-9f45313e054e",
        "status": "not_started",
        "streams_list": [
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_d",
            "language": "en",
            "main": false,
            "official": false,
            "raw_url": "https://www.twitch.tv/rlg_dota2_d"
          },
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_b",
            "language": "en",
            "main": true,
            "official": true,
            "raw_url": "https://www.twitch.tv/rlg_dota2_b"
          }
        ],
        "tournament_id": 17746,
        "winner_id": null,
        "winner_type": "Team"
      },
      {
        "begin_at": "2025-10-12T03:00:00Z",
        "detailed_stats": true,
        "draw": false,
        "end_at": null,
        "forfeit": false,
        "game_advantage": null,
        "id": 1249001,
        "live": {
          "opens_at": null,
          "supported": false,
          "url": null
        },
        "match_type": "best_of",
        "modified_at": "2025-10-03T16:01:29Z",
        "name": "Lower bracket final: TBD vs TBD",
        "number_of_games": 3,
        "original_scheduled_at": "2025-10-12T03:00:00Z",
        "rescheduled": false,
        "scheduled_at": "2025-10-12T03:00:00Z",
        "slug": "2025-10-12-812373cf-723f-4ec9-a623-a79e0e8810e0",
        "status": "not_started",
        "streams_list": [
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_d",
            "language": "en",
            "main": false,
            "official": false,
            "raw_url": "https://www.twitch.tv/rlg_dota2_d"
          },
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_b",
            "language": "en",
            "main": true,
            "official": true,
            "raw_url": "https://www.twitch.tv/rlg_dota2_b"
          }
        ],
        "tournament_id": 17746,
        "winner_id": null,
        "winner_type": "Team"
      },
      {
        "begin_at": "2025-10-12T07:00:00Z",
        "detailed_stats": true,
        "draw": false,
        "end_at": null,
        "forfeit": false,
        "game_advantage": null,
        "id": 1249002,
        "live": {
          "opens_at": null,
          "supported": false,
          "url": null
        },
        "match_type": "best_of",
        "modified_at": "2025-10-03T16:01:29Z",
        "name": "Grand final: TBD vs TBD",
        "number_of_games": 3,
        "original_scheduled_at": "2025-10-12T07:00:00Z",
        "rescheduled": false,
        "scheduled_at": "2025-10-12T07:00:00Z",
        "slug": "2025-10-12-02bf4711-18a0-467c-8776-a8b9c5e56a63",
        "status": "not_started",
        "streams_list": [
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_d",
            "language": "en",
            "main": false,
            "official": false,
            "raw_url": "https://www.twitch.tv/rlg_dota2_d"
          },
          {
            "embed_url": "https://player.twitch.tv/?channel=rlg_dota2_b",
            "language": "en",
            "main": true,
            "official": true,
            "raw_url": "https://www.twitch.tv/rlg_dota2_b"
          }
        ],
        "tournament_id": 17746,
        "winner_id": null,
        "winner_type": "Team"
      }
    ],
    "modified_at": "2025-10-03T16:01:29Z",
    "name": "Playoffs",
    "prizepool": null,
    "region": "ASIA",
    "serie": {
      "begin_at": "2025-10-10T03:00:00Z",
      "end_at": "2025-10-12T10:00:00Z",
      "full_name": "Southeast Asia Closed Qualifier season 5 2025",
      "id": 9767,
      "league_id": 5319,
      "modified_at": "2025-10-03T16:01:29Z",
      "name": "Southeast Asia Closed Qualifier",
      "season": "5",
      "slug": "dota-2-blast-slam-southeast-asia-closed-qualifier-5-2025",
      "winner_id": null,
      "winner_type": "Team",
      "year": 2025
    },
    "serie_id": 9767,
    "slug": "dota-2-blast-slam-southeast-asia-closed-qualifier-5-2025-playoffs",
    "teams": [
      {
        "acronym": "XctN",
        "dark_mode_image_url": null,
        "id": 1660,
        "image_url": "https://cdn.pandascore.co/images/team/image/1660/771px_execration_2024_full_allmode.png",
        "location": "PH",
        "modified_at": "2025-10-02T08:22:47Z",
        "name": "Execration",
        "slug": "execration"
      },
      {
        "acronym": "BOOM",
        "dark_mode_image_url": null,
        "id": 126229,
        "image_url": "https://cdn.pandascore.co/images/team/image/126229/boom-esports.png",
        "location": "ID",
        "modified_at": "2025-10-02T08:22:49Z",
        "name": "BOOM Esports",
        "slug": "boom-esports"
      },
      {
        "acronym": "TLN",
        "dark_mode_image_url": null,
        "id": 129862,
        "image_url": "https://cdn.pandascore.co/images/team/image/129862/900px_talon_esports_logo_2021.png",
        "location": "HK",
        "modified_at": "2025-09-26T21:07:51Z",
        "name": "Talon Esports",
        "slug": "talon-esports-dota-2"
      },
      {
        "acronym": "Nem",
        "dark_mode_image_url": "https://cdn.pandascore.co/dark_images/team/dark_image/136650/285px_team_nem_darkmode.png",
        "id": 136650,
        "image_url": "https://cdn.pandascore.co/images/team/image/136650/159px_team_nem_lightmode.png",
        "location": "PH",
        "modified_at": "2025-10-02T05:08:02Z",
        "name": "Team Nemesis",
        "slug": "team-nemesis"
      }
    ],
    "tier": "c",
    "type": "online",
    "videogame": {
      "id": 4,
      "name": "Dota 2",
      "slug": "dota-2"
    },
    "videogame_title": null,
    "winner_id": null,
    "winner_type": "Team"
  }
]
```

## Response Shape

Top-level JSON type: `array<object>`.

| field | type | required | description | constraints |
| --- | --- | --- | --- | --- |
| begin_at | string; format: date-time | yes | — | minLength=1; nullable |
| country | string | yes | Country code matching the location of the tournament according to the ISO 3166-1 standard (Alpha-2 code). In addition to the standard, the XK code is used for Kosovo. null if unknown | nullable |
| detailed_stats | boolean | yes | Whether the tournament is expected to have detailed statistics available | — |
| end_at | string; format: date-time | yes | — | minLength=1; nullable |
| expected_roster | array<object> | yes | — | — |
| has_bracket | boolean | yes | Whether the tournament has a bracket | — |
| id | integer | yes | — | minimum=1 |
| league | object | yes | — | — |
| league_id | integer | yes | — | minimum=1 |
| live_supported | boolean | yes | Whether live is supported | — |
| matches | array<object> | yes | — | — |
| modified_at | string; format: date-time | yes | — | minLength=1 |
| name | string | yes | — | — |
| prizepool | string | yes | — | nullable |
| region | string; enum: AF, ASIA, EEU, ME, NA, OCE, SA, WEU | yes | Region acronym for the location of the tournament. | nullable |
| serie | object | yes | — | — |
| serie_id | integer | yes | — | minimum=1 |
| slug | string | yes | — | minLength=1; pattern=^[a-z0-9_-]+$ |
| teams | array<object> | yes | — | — |
| tier | string; enum: a, b, c, d, s, unranked | yes | The tier of the tournament, ranging from 'S' to 'Unranked'. Ranking 'S' > 'A' > 'B' > 'C' > 'D' > 'Unranked' | nullable |
| type | string; enum: offline, online, online/offline | yes | Location type for a tournament | nullable |
| videogame | object; enum: {'id': 1, 'name': 'LoL', 'slug': 'league-of-legends'}, {'id': 3, 'name': 'Counter-Strike', 'slug': 'cs-go'}, {'id': 4, 'name': 'Dota 2', 'slug': 'dota-2'}, {'id': 14, 'name': 'Overwatch', 'slug': 'ow'}, {'id': 20, 'name': 'PUBG', 'slug': 'pubg'}, {'id': 22, 'name': 'Rocket League', 'slug': 'rl'}, {'id': 23, 'name': 'Call of Duty', 'slug': 'cod-mw'}, {'id': 24, 'name': 'Rainbow 6 Siege', 'slug': 'r6-siege'}, {'id': 25, 'name': 'EA Sports FC', 'slug': 'fifa'}, {'id': 26, 'name': 'Valorant', 'slug': 'valorant'}, {'id': 27, 'name': 'King of Glory', 'slug': 'kog'}, {'id': 28, 'name': 'LoL Wild Rift', 'slug': 'lol-wild-rift'}, {'id': 29, 'name': 'StarCraft 2', 'slug': 'starcraft-2'}, {'id': 30, 'name': 'StarCraft Brood War', 'slug': 'starcraft-brood-war'}, {'id': 31, 'name': 'eSoccer', 'slug': 'e-soccer'}, {'id': 32, 'name': 'eBasketball', 'slug': 'e-basketball'}, {'id': 33, 'name': 'eCricket', 'slug': 'e-cricket'}, {'id': 34, 'name': 'Mobile Legends: Bang Bang', 'slug': 'mlbb'}, {'id': 35, 'name': 'eHockey', 'slug': 'e-hockey'} | yes | — | — |
| videogame_title | object | yes | — | nullable |
| winner_id | unknown | yes | — | nullable |
| winner_type | string; enum: Player, Team | yes | — | nullable |

## Resource Relationships

| field | JSON type | endpoint-local description |
| --- | --- | --- |
| league | object | — |
| matches | array<object> | — |
| serie | object | — |
| teams | array<object> | — |
| videogame | object; enum: {'id': 1, 'name': 'LoL', 'slug': 'league-of-legends'}, {'id': 3, 'name': 'Counter-Strike', 'slug': 'cs-go'}, {'id': 4, 'name': 'Dota 2', 'slug': 'dota-2'}, {'id': 14, 'name': 'Overwatch', 'slug': 'ow'}, {'id': 20, 'name': 'PUBG', 'slug': 'pubg'}, {'id': 22, 'name': 'Rocket League', 'slug': 'rl'}, {'id': 23, 'name': 'Call of Duty', 'slug': 'cod-mw'}, {'id': 24, 'name': 'Rainbow 6 Siege', 'slug': 'r6-siege'}, {'id': 25, 'name': 'EA Sports FC', 'slug': 'fifa'}, {'id': 26, 'name': 'Valorant', 'slug': 'valorant'}, {'id': 27, 'name': 'King of Glory', 'slug': 'kog'}, {'id': 28, 'name': 'LoL Wild Rift', 'slug': 'lol-wild-rift'}, {'id': 29, 'name': 'StarCraft 2', 'slug': 'starcraft-2'}, {'id': 30, 'name': 'StarCraft Brood War', 'slug': 'starcraft-brood-war'}, {'id': 31, 'name': 'eSoccer', 'slug': 'e-soccer'}, {'id': 32, 'name': 'eBasketball', 'slug': 'e-basketball'}, {'id': 33, 'name': 'eCricket', 'slug': 'e-cricket'}, {'id': 34, 'name': 'Mobile Legends: Bang Bang', 'slug': 'mlbb'}, {'id': 35, 'name': 'eHockey', 'slug': 'e-hockey'} | — |
| winner_id | unknown | — |

## Source Notes

- Collection method: direct `.md` reference page, then its embedded OpenAPI JSON definition.
- Collected at: 2026-09-02T10:37:58.060537Z
- Authentication and response status alternatives are documented by PandaScore but are not reproduced here as request credentials.
