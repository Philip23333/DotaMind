# PandaScore Real Endpoint → DotaMind DTO Validation

Date: `2026-09-10T04:46:58.680775+00:00`  
Branch: `codex/model_behavior_optimization`  
Commit: `df23b03`  
Base URL: `https://api.pandascore.co`

## Summary

| Capability | Case | Result | Anomalies |
| --- | --- | --- | ---: |
| league.search | L1 league by id | PASS | 0 |
| league.search | L2 league by name | PASS | 0 |
| series.search | S1 series by id 10828 | PASS | 0 |
| series.search | S2 series by league/year | PASS | 0 |
| series.search | S3 series by id 4012 | PASS | 0 |
| series.teams | ST1 teams for series 10828 | PASS | 0 |
| tournament.search | T1 tournaments for series 10828 | PASS | 0 |
| tournament.search | T2 historical TI tournaments | PASS | 0 |
| match.search | M1 past matches for series 10828 | PASS | 0 |
| match.search | M2 past canceled matches | PASS | 0 |
| match.search | M3 upcoming matches | PASS | 0 |
| team.search | TEAM1 team by id 1669 | PASS | 0 |
| team.search | TEAM2 team by name | PASS | 0 |
| player.search | P1 player by id 27480 | PASS | 0 |
| player.search | P2 player by id 28009 | PASS | 0 |
| player.search | P3 active players for team 1669 | PASS | 0 |

The script reads `DOTAMIND_PANDASCORE_TOKEN` from the existing vNext
environment and never writes credentials to this report. Request entries below
contain only endpoint paths and query parameters. `ResponseAnomaly.path` values
use provider-source locations such as `provider.items[0].games[2]`.

## Cases

### L1 league by id

- Capability: `league.search`
- Status: `PASS`
- Query: `{
  "id": 4106,
  "name": null,
  "page": 1,
  "limit": 20
}`
- Request: `{
  "path": "/dota2/leagues",
  "params": {
    "page": 1,
    "per_page": 20,
    "filter[id]": 4106
  }
}`
- Raw summary: `{
  "item_count": 1,
  "item_types": {
    "dict": 1
  },
  "top_level_keys": [
    "id",
    "image_url",
    "modified_at",
    "name",
    "series",
    "slug",
    "url",
    "videogame"
  ],
  "role_values": []
}`
- DTO item count: `1`
- Anomaly count: `0`

DTO sample:
```json
[
  {
    "id": 4106,
    "name": "The International",
    "slug": "the-international",
    "image_url": "https://cdn-api.pandascore.co/images/league/image/4106/1200px-the_international_2023_lightmode-png"
  }
]
```

Anomalies:
```json
[]
```

### L2 league by name

- Capability: `league.search`
- Status: `PASS`
- Query: `{
  "id": null,
  "name": "The International",
  "page": 1,
  "limit": 20
}`
- Request: `{
  "path": "/dota2/leagues",
  "params": {
    "page": 1,
    "per_page": 20,
    "search[name]": "The International"
  }
}`
- Raw summary: `{
  "item_count": 1,
  "item_types": {
    "dict": 1
  },
  "top_level_keys": [
    "id",
    "image_url",
    "modified_at",
    "name",
    "series",
    "slug",
    "url",
    "videogame"
  ],
  "role_values": []
}`
- DTO item count: `1`
- Anomaly count: `0`

DTO sample:
```json
[
  {
    "id": 4106,
    "name": "The International",
    "slug": "the-international",
    "image_url": "https://cdn-api.pandascore.co/images/league/image/4106/1200px-the_international_2023_lightmode-png"
  }
]
```

Anomalies:
```json
[]
```

### S1 series by id 10828

- Capability: `series.search`
- Status: `PASS`
- Query: `{
  "id": 10828,
  "league_id": null,
  "name": null,
  "season": null,
  "year": null,
  "winner_id": null,
  "tier": null,
  "page": 1,
  "limit": 20
}`
- Request: `{
  "path": "/dota2/series",
  "params": {
    "page": 1,
    "per_page": 20,
    "filter[id]": 10828
  }
}`
- Raw summary: `{
  "item_count": 1,
  "item_types": {
    "dict": 1
  },
  "top_level_keys": [
    "begin_at",
    "end_at",
    "full_name",
    "id",
    "league",
    "league_id",
    "modified_at",
    "name",
    "season",
    "slug",
    "tournaments",
    "videogame",
    "videogame_title",
    "winner_id",
    "winner_type",
    "year"
  ],
  "role_values": []
}`
- DTO item count: `1`
- Anomaly count: `0`

DTO sample:
```json
[
  {
    "id": 10828,
    "league_id": 4106,
    "name": null,
    "full_name": "2026",
    "year": 2026,
    "season": null,
    "begin_at": "2026-08-12T22:00:00Z",
    "end_at": "2026-08-23T13:32:00Z",
    "winner_id": null,
    "tier": null,
    "slug": "the-international-2026"
  }
]
```

Anomalies:
```json
[]
```

### S2 series by league/year

- Capability: `series.search`
- Status: `PASS`
- Query: `{
  "id": null,
  "league_id": 4106,
  "name": null,
  "season": null,
  "year": 2026,
  "winner_id": null,
  "tier": null,
  "page": 1,
  "limit": 20
}`
- Request: `{
  "path": "/dota2/series",
  "params": {
    "page": 1,
    "per_page": 20,
    "filter[league_id]": 4106,
    "filter[year]": 2026
  }
}`
- Raw summary: `{
  "item_count": 16,
  "item_types": {
    "dict": 16
  },
  "top_level_keys": [
    "begin_at",
    "end_at",
    "full_name",
    "id",
    "league",
    "league_id",
    "modified_at",
    "name",
    "season",
    "slug",
    "tournaments",
    "videogame",
    "videogame_title",
    "winner_id",
    "winner_type",
    "year"
  ],
  "role_values": []
}`
- DTO item count: `16`
- Anomaly count: `0`

DTO sample:
```json
[
  {
    "id": 10828,
    "league_id": 4106,
    "name": null,
    "full_name": "2026",
    "year": 2026,
    "season": null,
    "begin_at": "2026-08-12T22:00:00Z",
    "end_at": "2026-08-23T13:32:00Z",
    "winner_id": null,
    "tier": null,
    "slug": "the-international-2026"
  },
  {
    "id": 10720,
    "league_id": 4106,
    "name": "Southeast Asia Closed Qualifier",
    "full_name": "Southeast Asia Closed Qualifier 2026",
    "year": 2026,
    "season": null,
    "begin_at": "2026-06-19T02:00:00Z",
    "end_at": "2026-06-23T13:00:00Z",
    "winner_id": null,
    "tier": null,
    "slug": "the-international-southeast-asia-closed-qualifier-2026"
  }
]
```

Anomalies:
```json
[]
```

### S3 series by id 4012

- Capability: `series.search`
- Status: `PASS`
- Query: `{
  "id": 4012,
  "league_id": null,
  "name": null,
  "season": null,
  "year": null,
  "winner_id": null,
  "tier": null,
  "page": 1,
  "limit": 20
}`
- Request: `{
  "path": "/dota2/series",
  "params": {
    "page": 1,
    "per_page": 20,
    "filter[id]": 4012
  }
}`
- Raw summary: `{
  "item_count": 1,
  "item_types": {
    "dict": 1
  },
  "top_level_keys": [
    "begin_at",
    "end_at",
    "full_name",
    "id",
    "league",
    "league_id",
    "modified_at",
    "name",
    "season",
    "slug",
    "tournaments",
    "videogame",
    "videogame_title",
    "winner_id",
    "winner_type",
    "year"
  ],
  "role_values": []
}`
- DTO item count: `1`
- Anomaly count: `0`

DTO sample:
```json
[
  {
    "id": 4012,
    "league_id": 4106,
    "name": null,
    "full_name": "Season 10 2021",
    "year": 2021,
    "season": "10",
    "begin_at": "2021-10-06T22:00:00Z",
    "end_at": "2021-10-17T17:49:00Z",
    "winner_id": 1669,
    "tier": null,
    "slug": "the-international-10-2021"
  }
]
```

Anomalies:
```json
[]
```

### ST1 teams for series 10828

- Capability: `series.teams`
- Status: `PASS`
- Query: `{
  "series_id": 10828,
  "page": 1,
  "limit": 20
}`
- Request: `{
  "path": "/dota2/series/10828/teams",
  "params": {
    "page": 1,
    "per_page": 20
  }
}`
- Raw summary: `{
  "item_count": 16,
  "item_types": {
    "dict": 16
  },
  "top_level_keys": [
    "acronym",
    "current_videogame",
    "dark_mode_image_url",
    "id",
    "image_url",
    "location",
    "modified_at",
    "name",
    "players",
    "slug"
  ],
  "role_values": [
    "1",
    "2",
    "3",
    "5",
    "4"
  ]
}`
- DTO item count: `16`
- Anomaly count: `0`

DTO sample:
```json
[
  {
    "id": 138994,
    "name": "Iron Wing",
    "acronym": "IW",
    "location": "RU",
    "slug": "iron-wing",
    "image_url": "https://cdn-api.pandascore.co/images/team/image/138994/10150413.png"
  },
  {
    "id": 138993,
    "name": "BoomBoys",
    "acronym": "BB",
    "location": "RU",
    "slug": "boomboys",
    "image_url": "https://cdn-api.pandascore.co/images/team/image/138993/800px_boom_boys_allmode.png"
  }
]
```

Anomalies:
```json
[]
```

### T1 tournaments for series 10828

- Capability: `tournament.search`
- Status: `PASS`
- Query: `{
  "id": null,
  "series_id": 10828,
  "name": null,
  "page": 1,
  "limit": 20
}`
- Request: `{
  "path": "/dota2/tournaments",
  "params": {
    "page": 1,
    "per_page": 20,
    "filter[serie_id]": 10828
  }
}`
- Raw summary: `{
  "item_count": 3,
  "item_types": {
    "dict": 3
  },
  "top_level_keys": [
    "begin_at",
    "country",
    "detailed_stats",
    "end_at",
    "expected_roster",
    "has_bracket",
    "id",
    "league",
    "league_id",
    "live_supported",
    "matches",
    "modified_at",
    "name",
    "prizepool",
    "region",
    "serie",
    "serie_id",
    "slug",
    "teams",
    "tier",
    "type",
    "videogame",
    "videogame_title",
    "winner_id",
    "winner_type"
  ],
  "role_values": [
    "3",
    "2",
    "1",
    "4",
    "5"
  ]
}`
- DTO item count: `3`
- Anomaly count: `0`

DTO sample:
```json
[
  {
    "id": 21698,
    "series_id": 10828,
    "league_id": 4106,
    "name": "Playoffs",
    "type": "offline",
    "country": null,
    "region": "ASIA",
    "begin_at": "2026-08-20T02:00:00Z",
    "end_at": "2026-08-23T13:32:00Z",
    "winner_id": 1669,
    "tier": "s",
    "prizepool": "3061178 United States Dollar",
    "has_bracket": true,
    "slug": "the-international-2026-playoffs",
    "participants": [
      {
        "team": {
          "id": 1647,
          "name": "Team Liquid",
          "acronym": "Liquid",
          "location": "NL",
          "slug": "team-liquid",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/1647/527px_team_liquid_2023_lightmode.png"
        },
        "expected_roster": [
          {
            "id": 9450,
            "name": "Ace",
            "first_name": "Marcus Folke",
            "last_name": "Hoelgaard Christensen",
            "nationality": "DK",
            "slug": "ace"
          },
          {
            "id": 9461,
            "name": "Nisha",
            "first_name": "Michał",
            "last_name": "Jankowski",
            "nationality": "PL",
            "slug": "nisha"
          },
          {
            "id": 9596,
            "name": "miCKe",
            "first_name": "Michael",
            "last_name": "Vu",
            "nationality": "SE",
            "slug": "micke"
          },
          {
            "id": 13848,
            "name": "Boxi",
            "first_name": "Samuel",
            "last_name": "Svahn",
            "nationality": "SE",
            "slug": "bomboclan"
          },
          {
            "id": 31555,
            "name": "tOfu",
            "first_name": "Erik",
            "last_name": "Engel",
            "nationality": "DE",
            "slug": "tofu"
          }
        ]
      },
      {
        "team": {
          "id": 1669,
          "name": "Team Spirit",
          "acronym": "TS",
          "location": "RU",
          "slug": "team-spirit",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/1669/153px_team_spirit_2022_lightmode.png"
        },
        "expected_roster": [
          {
            "id": 26727,
            "name": "Collapse",
            "first_name": "Magomed",
            "last_name": "Khalilov",
            "nationality": "RU",
            "slug": "collapse"
          },
          {
            "id": 27480,
            "name": "Larl",
            "first_name": "Denis",
            "last_name": "Sigitov",
            "nationality": "RU",
            "slug": "larl"
          },
          {
            "id": 30258,
            "name": "Yatoro",
            "first_name": "Ilya",
            "last_name": "Mulyarchuk",
            "nationality": "UA",
            "slug": "yatoro"
          },
          {
            "id": 49070,
            "name": "rue",
            "first_name": "Aleksandr",
            "last_name": "Filin",
            "nationality": "RU",
            "slug": "rue"
          },
          {
            "id": 54351,
            "name": "not me",
            "first_name": "Alexey",
            "last_name": "Kosmynin",
            "nationality": "RU",
            "slug": "notme"
          }
        ]
      },
      {
        "team": {
          "id": 129609,
          "name": "Nigma Galaxy",
          "acronym": "NGX",
          "location": "AE",
          "slug": "nigma-galaxy",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/129609/614985375154c.png"
        },
        "expected_roster": [
          {
            "id": 9341,
            "name": "GH",
            "first_name": "Maroun",
            "last_name": "Merhej",
            "nationality": "LB",
            "slug": "gh"
          },
          {
            "id": 9368,
            "name": "SumaiL",
            "first_name": "Syed Sumail",
            "last_name": "Hassan",
            "nationality": "PK",
            "slug": "sumail"
          },
          {
            "id": 26929,
            "name": "lorenof",
            "first_name": "Artem",
            "last_name": "Melnik",
            "nationality": "UA",
            "slug": "lorenof"
          },
          {
            "id": 28075,
            "name": "Davai Lama",
            "first_name": "Cedric",
            "last_name": "Deckmyn",
            "nationality": "BE",
            "slug": "davai-lama"
          },
          {
            "id": 33521,
            "name": "OmaR",
            "first_name": "Omar",
            "last_name": "Moughrabi",
            "nationality": "LB",
            "slug": "omar"
          }
        ]
      },
      {
        "team": {
          "id": 133868,
          "name": "Team Falcons",
          "acronym": "FLC",
          "location": "SA",
          "slug": "team-falcons-dota-2",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/133868/team_falconslogo_square.png"
        },
        "expected_roster": [
          {
            "id": 9372,
            "name": "Cr1t-",
            "first_name": "Andreas Franck",
            "last_name": "Nielsen",
            "nationality": "DK",
            "slug": "cr1t"
          },
          {
            "id": 9493,
            "name": "Sneyking",
            "first_name": "Jingjun",
            "last_name": "Wu",
            "nationality": "US",
            "slug": "sneyking"
          },
          {
            "id": 9612,
            "name": "skiter",
            "first_name": "Oliver",
            "last_name": "Lepko",
            "nationality": "SK",
            "slug": "c64-oliver"
          },
          {
            "id": 31707,
            "name": "Malr1ne",
            "first_name": "Potorak",
            "last_name": "Stanislav",
            "nationality": "RU",
            "slug": "malr1ne"
          },
          {
            "id": 31708,
            "name": "ATF",
            "first_name": "Ammar",
            "last_name": "Assaf",
            "nationality": "JO",
            "slug": "ammar_the_fucker"
          }
        ]
      },
      {
        "team": {
          "id": 137073,
          "name": "Team Yandex",
          "acronym": "TY",
          "location": "RU",
          "slug": "team-yandex",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/137073/249px_team_yandex_allmode.png"
        },
        "expected_roster": [
          {
            "id": 9495,
            "name": "Saksa",
            "first_name": "Martin",
            "last_name": "Sazdov",
            "nationality": "MK",
            "slug": "saksa"
          },
          {
            "id": 12509,
            "name": "DM",
            "first_name": "Dmitry",
            "last_name": "Dorokhin",
            "nationality": "RU",
            "slug": "maybe-once"
          },
          {
            "id": 24551,
            "name": "watson",
            "first_name": "Alimzhan",
            "last_name": "Islambekov",
            "nationality": "KZ",
            "slug": "nezuko"
          },
          {
            "id": 33877,
            "name": "Malady",
            "first_name": "Arman",
            "last_name": "Orazbaev",
            "nationality": "KZ",
            "slug": "0e378d57-903a-4758-a624-de5cfca72d68"
          },
          {
            "id": 35696,
            "name": "Chira JUNIOR",
            "first_name": "Ilya",
            "last_name": "Chirtsov",
            "nationality": "RU",
            "slug": "chira-junior"
          }
        ]
      },
      {
        "team": {
          "id": 138839,
          "name": "TEAM VISION",
          "acronym": "VSN",
          "location": "RU",
          "slug": "team-vision-dota-2",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/138839/619px_team_vision_allmode.png"
        },
        "expected_roster": [
          {
            "id": 9360,
            "name": "No[o]ne",
            "first_name": "Vladimir",
            "last_name": "Minenko",
         
... [DTO sample truncated]
```

Anomalies:
```json
[]
```

### T2 historical TI tournaments

- Capability: `tournament.search`
- Status: `PASS`
- Query: `{
  "id": null,
  "series_id": 4012,
  "name": null,
  "page": 1,
  "limit": 20
}`
- Request: `{
  "path": "/dota2/tournaments",
  "params": {
    "page": 1,
    "per_page": 20,
    "filter[serie_id]": 4012
  }
}`
- Raw summary: `{
  "item_count": 3,
  "item_types": {
    "dict": 3
  },
  "top_level_keys": [
    "begin_at",
    "country",
    "detailed_stats",
    "end_at",
    "expected_roster",
    "has_bracket",
    "id",
    "league",
    "league_id",
    "live_supported",
    "matches",
    "modified_at",
    "name",
    "prizepool",
    "region",
    "serie",
    "serie_id",
    "slug",
    "teams",
    "tier",
    "type",
    "videogame",
    "videogame_title",
    "winner_id",
    "winner_type"
  ],
  "role_values": [
    "3",
    "2",
    "1",
    "4",
    "5"
  ]
}`
- DTO item count: `3`
- Anomaly count: `0`

DTO sample:
```json
[
  {
    "id": 6868,
    "series_id": 4012,
    "league_id": 4106,
    "name": "Playoffs",
    "type": null,
    "country": null,
    "region": null,
    "begin_at": "2021-10-12T07:00:00Z",
    "end_at": "2021-10-17T17:49:00Z",
    "winner_id": 1669,
    "tier": "s",
    "prizepool": "40018195 United States Dollar",
    "has_bracket": true,
    "slug": "the-international-10-2021-playoffs",
    "participants": [
      {
        "team": {
          "id": 1651,
          "name": "Virtus.pro",
          "acronym": "VP",
          "location": "RU",
          "slug": "virtus-pro",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/1651/921px_virtus.pro_2019_allmode.png"
        },
        "expected_roster": [
          {
            "id": 12509,
            "name": "DM",
            "first_name": "Dmitry",
            "last_name": "Dorokhin",
            "nationality": "RU",
            "slug": "maybe-once"
          },
          {
            "id": 23103,
            "name": "gpk",
            "first_name": "Danil",
            "last_name": "Skutin",
            "nationality": "RU",
            "slug": "gpk"
          },
          {
            "id": 23715,
            "name": "Nightfall",
            "first_name": "Egor",
            "last_name": "Grigorenko",
            "nationality": "RU",
            "slug": "epileptick1d"
          },
          {
            "id": 23897,
            "name": "Save-",
            "first_name": "Vitalie",
            "last_name": "Melnic",
            "nationality": "MD",
            "slug": "save-vitalie-melnic"
          },
          {
            "id": 25248,
            "name": "Kingslayer",
            "first_name": "Ilyas",
            "last_name": "Ganeev",
            "nationality": "RU",
            "slug": "illias"
          }
        ]
      },
      {
        "team": {
          "id": 1653,
          "name": "Evil Geniuses",
          "acronym": "EG",
          "location": "US",
          "slug": "evil-geniuses-dota-2",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/1653/152px_evil_geniuses_2020_lightmode.png"
        },
        "expected_roster": [
          {
            "id": 9369,
            "name": "Arteezy",
            "first_name": "Artour",
            "last_name": "Babaev",
            "nationality": "CA",
            "slug": "rtz-yb-a"
          },
          {
            "id": 9372,
            "name": "Cr1t-",
            "first_name": "Andreas Franck",
            "last_name": "Nielsen",
            "nationality": "DK",
            "slug": "cr1t"
          },
          {
            "id": 9373,
            "name": "Fly",
            "first_name": "Tal",
            "last_name": "Aizik",
            "nationality": "IL",
            "slug": "fly-tal-aizik"
          },
          {
            "id": 9394,
            "name": "Abed",
            "first_name": "Abed Azel L.",
            "last_name": "Yusop",
            "nationality": "PH",
            "slug": "abed"
          },
          {
            "id": 9662,
            "name": "iceiceice",
            "first_name": "Daryl Koh",
            "last_name": "Pei Xiang",
            "nationality": "SG",
            "slug": "daryl-koh-pei-xiang"
          }
        ]
      },
      {
        "team": {
          "id": 1654,
          "name": "OG",
          "acronym": "OG",
          "location": null,
          "slug": "og",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/1654/438px_og_2026_allmode.png"
        },
        "expected_roster": [
          {
            "id": 9368,
            "name": "SumaiL",
            "first_name": "Syed Sumail",
            "last_name": "Hassan",
            "nationality": "PK",
            "slug": "sumail"
          },
          {
            "id": 9377,
            "name": "N0tail",
            "first_name": "Johan",
            "last_name": "Sundstein",
            "nationality": "DK",
            "slug": "bigdaddyn0tail"
          },
          {
            "id": 9495,
            "name": "Saksa",
            "first_name": "Martin",
            "last_name": "Sazdov",
            "nationality": "MK",
            "slug": "saksa"
          },
          {
            "id": 10000,
            "name": "TOPSON",
            "first_name": "Topias",
            "last_name": "Taavitsainen",
            "nationality": "FI",
            "slug": "topson"
          },
          {
            "id": 10930,
            "name": "Ceb",
            "first_name": "Sébastien",
            "last_name": "Debs",
            "nationality": "FR",
            "slug": "7ckngmad"
          }
        ]
      },
      {
        "team": {
          "id": 1656,
          "name": "Team Secret",
          "acronym": "Secret",
          "location": null,
          "slug": "team-secret",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/1656/Team_Secret.png"
        },
        "expected_roster": [
          {
            "id": 9342,
            "name": "MATUMBAMAN",
            "first_name": "Lasse Aukusti",
            "last_name": "Urpalainen",
            "nationality": "FI",
            "slug": "matumbaman"
          },
          {
            "id": 9371,
            "name": "zai",
            "first_name": "Ludwig",
            "last_name": "Wåhlberg",
            "nationality": "SE",
            "slug": "zai"
          },
          {
            "id": 9383,
            "name": "Puppey",
            "first_name": "Clement",
            "last_name": "Ivanov",
            "nationality": "EE",
            "slug": "puppey"
          },
          {
            "id": 9384,
            "name": "YapzOr",
            "first_name": "Yazied",
            "last_name": "Jaradat",
            "nationality": "JO",
            "slug": "yapzor"
          },
          {
            "id": 9461,
            "name": "Nisha",
            "first_name": "Michał",
            "last_name": "Jankowski",
            "nationality": "PL",
            "slug": "nisha"
          }
        ]
      },
      {
        "team": {
          "id": 1657,
          "name": "LGD Gaming",
          "acronym": "LGD",
          "location": "CN",
          "slug": "lgd-gaming-dota-2",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/1657/600px_lgd_gaming_dec_2019_allmode.png"
        },
        "expected_roster": [
          {
            "id": 9530,
            "name": "XinQ",
            "first_name": "Zixing",
            "last_name": "Zhao",
            "nationality": "CN",
            "slug": "xinq"
          },
          {
            "id": 9535,
            "name": "Bach",
            "first_name": "Zhang",
            "last_name": "Ruida",
            "nationality": "CN",
            "slug": "faith_bian"
          },
          {
            "id": 9537,
            "name": "y`",
            "first_name": "Yiping",
            "last_name": "Zhang",
            "nationality": "CN",
            "slug": "y"
          },
          {
            "id": 9916,
            "name": "Ame",
            "first_name": "Chunyu",
            "last_name": "Wang",
            "nationality": "CN",
            "slug": "ame"
          },
          {
            "id": 15535,
            "name": "NothingToSay",
            "first_name": "Jinxiang",
            "last_name": "Cheng",
            "nationality": "MY",
            "slug": "nothingtosay"
          }
        ]
      },
      {
        "team": {
          "id": 1662,
          "name": "Invictus Gaming",
          "acronym": "iG",
          "location": "CN",
          "slug": "invictus-gaming-dota-2",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/1662/148px_invictus_gaming_lightmode.png"
        },
        "expected_roster": [
          {
            "id": 9366,
            "name": "Kaka",
            "first_name": "Liangzhi",
            "last_name": "Hu",
            "nationality": "CN",
            "
... [DTO sample truncated]
```

Anomalies:
```json
[]
```

### M1 past matches for series 10828

- Capability: `match.search`
- Status: `PASS`
- Query: `{
  "id": null,
  "league_id": null,
  "series_id": 10828,
  "tournament_id": null,
  "team_id": null,
  "name": null,
  "status": null,
  "winner_id": null,
  "lifecycle": "past",
  "sort": null,
  "page": 1,
  "limit": 10
}`
- Request: `{
  "path": "/dota2/matches/past",
  "params": {
    "page": 1,
    "per_page": 10,
    "filter[serie_id]": 10828
  }
}`
- Raw summary: `{
  "item_count": 10,
  "item_types": {
    "dict": 10
  },
  "top_level_keys": [
    "begin_at",
    "detailed_stats",
    "draw",
    "end_at",
    "forfeit",
    "game_advantage",
    "games",
    "id",
    "league",
    "league_id",
    "live",
    "match_type",
    "modified_at",
    "name",
    "number_of_games",
    "opponents",
    "original_scheduled_at",
    "rescheduled",
    "results",
    "scheduled_at",
    "serie",
    "serie_id",
    "slug",
    "status",
    "streams_list",
    "tournament",
    "tournament_id",
    "videogame",
    "videogame_title",
    "videogame_version",
    "winner",
    "winner_id",
    "winner_type"
  ],
  "role_values": []
}`
- DTO item count: `10`
- Anomaly count: `0`

DTO sample:
```json
[
  {
    "id": 1638249,
    "name": "Grand final: VSN vs TS",
    "slug": "team-vision-2026-08-23",
    "status": "finished",
    "match_type": "best_of",
    "number_of_games": 5,
    "begin_at": "2026-08-23T06:19:11Z",
    "end_at": "2026-08-23T13:32:59Z",
    "scheduled_at": "2026-08-23T06:15:00Z",
    "original_scheduled_at": "2026-08-23T05:00:00Z",
    "league_id": 4106,
    "series_id": 10828,
    "tournament_id": 21698,
    "participants": [
      {
        "team": {
          "id": 138839,
          "name": "TEAM VISION",
          "acronym": "VSN",
          "location": "RU",
          "slug": "team-vision-dota-2",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/138839/619px_team_vision_allmode.png"
        },
        "score": 2
      },
      {
        "team": {
          "id": 1669,
          "name": "Team Spirit",
          "acronym": "TS",
          "location": "RU",
          "slug": "team-spirit",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/1669/153px_team_spirit_2022_lightmode.png"
        },
        "score": 3
      }
    ],
    "winner_id": 1669,
    "winner": {
      "id": 1669,
      "name": "Team Spirit",
      "acronym": "TS",
      "location": "RU",
      "slug": "team-spirit",
      "image_url": "https://cdn-api.pandascore.co/images/team/image/1669/153px_team_spirit_2022_lightmode.png"
    },
    "games": [
      {
        "id": 738793,
        "position": 1,
        "status": "finished",
        "begin_at": "2026-08-23T06:19:11Z",
        "end_at": "2026-08-23T07:20:26Z",
        "length": 2775,
        "winner_id": 1669,
        "complete": true,
        "forfeit": false
      },
      {
        "id": 738794,
        "position": 2,
        "status": "finished",
        "begin_at": "2026-08-23T07:38:57Z",
        "end_at": "2026-08-23T08:59:33Z",
        "length": 3869,
        "winner_id": 138839,
        "complete": true,
        "forfeit": false
      },
      {
        "id": 738795,
        "position": 3,
        "status": "finished",
        "begin_at": "2026-08-23T09:16:39Z",
        "end_at": "2026-08-23T10:18:45Z",
        "length": 2756,
        "winner_id": 1669,
        "complete": true,
        "forfeit": false
      },
      {
        "id": 738796,
        "position": 4,
        "status": "finished",
        "begin_at": "2026-08-23T10:52:14Z",
        "end_at": "2026-08-23T11:51:58Z",
        "length": 2658,
        "winner_id": 138839,
        "complete": true,
        "forfeit": false
      },
      {
        "id": 738797,
        "position": 5,
        "status": "finished",
        "begin_at": "2026-08-23T12:10:53Z",
        "end_at": "2026-08-23T13:32:59Z",
        "length": 3862,
        "winner_id": 1669,
        "complete": true,
        "forfeit": false
      }
    ],
    "draw": false,
    "forfeit": false,
    "rescheduled": true
  },
  {
    "id": 1638239,
    "name": "Lower bracket final: TY vs TS",
    "slug": "team-yandex-2026-08-23",
    "status": "finished",
    "match_type": "best_of",
    "number_of_games": 3,
    "begin_at": "2026-08-23T02:13:23Z",
    "end_at": "2026-08-23T04:12:18Z",
    "scheduled_at": "2026-08-23T02:10:00Z",
    "original_scheduled_at": "2026-08-23T02:00:00Z",
    "league_id": 4106,
    "series_id": 10828,
    "tournament_id": 21698,
    "participants": [
      {
        "team": {
          "id": 137073,
          "name": "Team Yandex",
          "acronym": "TY",
          "location": "RU",
          "slug": "team-yandex",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/137073/249px_team_yandex_allmode.png"
        },
        "score": 0
      },
      {
        "team": {
          "id": 1669,
          "name": "Team Spirit",
          "acronym": "TS",
          "location": "RU",
          "slug": "team-spirit",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/1669/153px_team_spirit_2022_lightmode.png"
        },
        "score": 2
      }
    ],
    "winner_id": 1669,
    "winner": {
      "id": 1669,
      "name": "Team Spirit",
      "acronym": "TS",
      "location": "RU",
      "slug": "team-spirit",
      "image_url": "https://cdn-api.pandascore.co/images/team/image/1669/153px_team_spirit_2022_lightmode.png"
    },
    "games": [
      {
        "id": 738790,
        "position": 1,
        "status": "finished",
        "begin_at": "2026-08-23T02:13:24Z",
        "end_at": "2026-08-23T03:05:22Z",
        "length": 2245,
        "winner_id": 1669,
        "complete": true,
        "forfeit": false
      },
      {
        "id": 738791,
        "position": 2,
        "status": "finished",
        "begin_at": "2026-08-23T03:22:43Z",
        "end_at": "2026-08-23T04:12:18Z",
        "length": 2059,
        "winner_id": 1669,
        "complete": true,
        "forfeit": false
      }
    ],
    "draw": false,
    "forfeit": false,
    "rescheduled": true
  }
]
```

Anomalies:
```json
[]
```

### M2 past canceled matches

- Capability: `match.search`
- Status: `PASS`
- Query: `{
  "id": null,
  "league_id": null,
  "series_id": null,
  "tournament_id": null,
  "team_id": null,
  "name": null,
  "status": "canceled",
  "winner_id": null,
  "lifecycle": "past",
  "sort": null,
  "page": 1,
  "limit": 10
}`
- Request: `{
  "path": "/dota2/matches/past",
  "params": {
    "page": 1,
    "per_page": 10,
    "filter[status]": "canceled"
  }
}`
- Raw summary: `{
  "item_count": 10,
  "item_types": {
    "dict": 10
  },
  "top_level_keys": [
    "begin_at",
    "detailed_stats",
    "draw",
    "end_at",
    "forfeit",
    "game_advantage",
    "games",
    "id",
    "league",
    "league_id",
    "live",
    "match_type",
    "modified_at",
    "name",
    "number_of_games",
    "opponents",
    "original_scheduled_at",
    "rescheduled",
    "results",
    "scheduled_at",
    "serie",
    "serie_id",
    "slug",
    "status",
    "streams_list",
    "tournament",
    "tournament_id",
    "videogame",
    "videogame_title",
    "videogame_version",
    "winner",
    "winner_id",
    "winner_type"
  ],
  "role_values": []
}`
- DTO item count: `10`
- Anomaly count: `0`

DTO sample:
```json
[
  {
    "id": 1659341,
    "name": "Upper bracket final: Na`Vi vs GL",
    "slug": "natus-vincere-2026-09-09",
    "status": "canceled",
    "match_type": "best_of",
    "number_of_games": 3,
    "begin_at": null,
    "end_at": null,
    "scheduled_at": "2026-09-09T10:00:00Z",
    "original_scheduled_at": "2026-09-09T09:00:00Z",
    "league_id": 5544,
    "series_id": 10909,
    "tournament_id": 21798,
    "participants": [
      {
        "team": {
          "id": 1699,
          "name": "Natus Vincere",
          "acronym": "Na`Vi",
          "location": "UA",
          "slug": "natus-vincere",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/1699/Na_vi_logo.png"
        },
        "score": 0
      },
      {
        "team": {
          "id": 137588,
          "name": "GamerLegion",
          "acronym": "GL",
          "location": "US",
          "slug": "gamerlegion-dota-2",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/137588/900px_gamer_legion_cs_2023_allmode.png"
        },
        "score": 0
      }
    ],
    "winner_id": 1699,
    "winner": {
      "id": 1699,
      "name": "Natus Vincere",
      "acronym": "Na`Vi",
      "location": "UA",
      "slug": "natus-vincere",
      "image_url": "https://cdn-api.pandascore.co/images/team/image/1699/Na_vi_logo.png"
    },
    "games": [
      {
        "id": 739000,
        "position": 1,
        "status": "not_started",
        "begin_at": null,
        "end_at": null,
        "length": null,
        "winner_id": null,
        "complete": false,
        "forfeit": false
      },
      {
        "id": 739001,
        "position": 2,
        "status": "not_started",
        "begin_at": null,
        "end_at": null,
        "length": null,
        "winner_id": null,
        "complete": false,
        "forfeit": false
      },
      {
        "id": 739002,
        "position": 3,
        "status": "not_started",
        "begin_at": null,
        "end_at": null,
        "length": null,
        "winner_id": null,
        "complete": false,
        "forfeit": false
      }
    ],
    "draw": false,
    "forfeit": true,
    "rescheduled": true
  },
  {
    "id": 1659901,
    "name": "4iki vs PR",
    "slug": "re-arise-vs-power-rangers-2026-09-03",
    "status": "canceled",
    "match_type": "best_of",
    "number_of_games": 3,
    "begin_at": null,
    "end_at": null,
    "scheduled_at": "2026-09-03T18:00:00Z",
    "original_scheduled_at": "2026-09-03T18:00:00Z",
    "league_id": 5544,
    "series_id": 10909,
    "tournament_id": 21796,
    "participants": [
      {
        "team": {
          "id": 138761,
          "name": "4ikibamboni",
          "acronym": "4iki",
          "location": null,
          "slug": "4ikibamboni",
          "image_url": null
        },
        "score": 0
      },
      {
        "team": {
          "id": 137870,
          "name": "Power Rangers",
          "acronym": "PR",
          "location": null,
          "slug": "power-rangers-dota-2",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/137870/power_rangers_lightmode.png"
        },
        "score": 0
      }
    ],
    "winner_id": 137870,
    "winner": {
      "id": 137870,
      "name": "Power Rangers",
      "acronym": "PR",
      "location": null,
      "slug": "power-rangers-dota-2",
      "image_url": "https://cdn-api.pandascore.co/images/team/image/137870/power_rangers_lightmode.png"
    },
    "games": [
      {
        "id": 739083,
        "position": 1,
        "status": "not_started",
        "begin_at": null,
        "end_at": null,
        "length": null,
        "winner_id": null,
        "complete": false,
        "forfeit": false
      },
      {
        "id": 739084,
        "position": 2,
        "status": "not_started",
        "begin_at": null,
        "end_at": null,
        "length": null,
        "winner_id": null,
        "complete": false,
        "forfeit": false
      },
      {
        "id": 739085,
        "position": 3,
        "status": "not_started",
        "begin_at": null,
        "end_at": null,
        "length": null,
        "winner_id": null,
        "complete": false,
        "forfeit": false
      }
    ],
    "draw": false,
    "forfeit": true,
    "rescheduled": false
  }
]
```

Anomalies:
```json
[]
```

### M3 upcoming matches

- Capability: `match.search`
- Status: `PASS`
- Query: `{
  "id": null,
  "league_id": null,
  "series_id": null,
  "tournament_id": null,
  "team_id": null,
  "name": null,
  "status": null,
  "winner_id": null,
  "lifecycle": "upcoming",
  "sort": null,
  "page": 1,
  "limit": 10
}`
- Request: `{
  "path": "/dota2/matches/upcoming",
  "params": {
    "page": 1,
    "per_page": 10
  }
}`
- Raw summary: `{
  "item_count": 10,
  "item_types": {
    "dict": 10
  },
  "top_level_keys": [
    "begin_at",
    "detailed_stats",
    "draw",
    "end_at",
    "forfeit",
    "game_advantage",
    "games",
    "id",
    "league",
    "league_id",
    "live",
    "match_type",
    "modified_at",
    "name",
    "number_of_games",
    "opponents",
    "original_scheduled_at",
    "rescheduled",
    "results",
    "scheduled_at",
    "serie",
    "serie_id",
    "slug",
    "status",
    "streams_list",
    "tournament",
    "tournament_id",
    "videogame",
    "videogame_title",
    "videogame_version",
    "winner",
    "winner_id",
    "winner_type"
  ],
  "role_values": []
}`
- DTO item count: `10`
- Anomaly count: `0`

DTO sample:
```json
[
  {
    "id": 1659344,
    "name": "Lower bracket final: GL vs KS",
    "slug": "gamerlegion-2026-09-10",
    "status": "not_started",
    "match_type": "best_of",
    "number_of_games": 3,
    "begin_at": "2026-09-10T11:00:00Z",
    "end_at": null,
    "scheduled_at": "2026-09-10T11:00:00Z",
    "original_scheduled_at": "2026-09-10T11:00:00Z",
    "league_id": 5544,
    "series_id": 10909,
    "tournament_id": 21798,
    "participants": [
      {
        "team": {
          "id": 137588,
          "name": "GamerLegion",
          "acronym": "GL",
          "location": "US",
          "slug": "gamerlegion-dota-2",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/137588/900px_gamer_legion_cs_2023_allmode.png"
        },
        "score": 0
      },
      {
        "team": {
          "id": 133873,
          "name": "Klim Sani4",
          "acronym": "KS",
          "location": "RU",
          "slug": "klim-sani4",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/133873/649px_klim_sani4_lightmode.png"
        },
        "score": 0
      }
    ],
    "winner_id": null,
    "winner": null,
    "games": [
      {
        "id": 739008,
        "position": 1,
        "status": "not_started",
        "begin_at": null,
        "end_at": null,
        "length": null,
        "winner_id": null,
        "complete": false,
        "forfeit": false
      },
      {
        "id": 739009,
        "position": 2,
        "status": "not_started",
        "begin_at": null,
        "end_at": null,
        "length": null,
        "winner_id": null,
        "complete": false,
        "forfeit": false
      },
      {
        "id": 739010,
        "position": 3,
        "status": "not_started",
        "begin_at": null,
        "end_at": null,
        "length": null,
        "winner_id": null,
        "complete": false,
        "forfeit": false
      }
    ],
    "draw": false,
    "forfeit": false,
    "rescheduled": false
  },
  {
    "id": 1680158,
    "name": "Recrent Club vs Daxak Club",
    "slug": "recrent-club-vs-daxak-club-2026-09-10-da950d29-b69c-4613-9aea-6e4fbad26ae3",
    "status": "not_started",
    "match_type": "best_of",
    "number_of_games": 3,
    "begin_at": "2026-09-10T12:00:00Z",
    "end_at": null,
    "scheduled_at": "2026-09-10T12:00:00Z",
    "original_scheduled_at": "2026-09-10T12:00:00Z",
    "league_id": 5490,
    "series_id": 10955,
    "tournament_id": 21887,
    "participants": [
      {
        "team": {
          "id": 139232,
          "name": "Recrent Club",
          "acronym": null,
          "location": "RU",
          "slug": "recrent-club-dota-2",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/139232/recrent_club.png"
        },
        "score": 0
      },
      {
        "team": {
          "id": 138719,
          "name": "Daxak Club",
          "acronym": null,
          "location": "RU",
          "slug": "daxak-team",
          "image_url": "https://cdn-api.pandascore.co/images/team/image/138719/554px_daxak_club_allmode.png"
        },
        "score": 0
      }
    ],
    "winner_id": null,
    "winner": null,
    "games": [
      {
        "id": 739259,
        "position": 1,
        "status": "not_started",
        "begin_at": null,
        "end_at": null,
        "length": null,
        "winner_id": null,
        "complete": false,
        "forfeit": false
      },
      {
        "id": 739260,
        "position": 2,
        "status": "not_started",
        "begin_at": null,
        "end_at": null,
        "length": null,
        "winner_id": null,
        "complete": false,
        "forfeit": false
      },
      {
        "id": 739261,
        "position": 3,
        "status": "not_started",
        "begin_at": null,
        "end_at": null,
        "length": null,
        "winner_id": null,
        "complete": false,
        "forfeit": false
      }
    ],
    "draw": false,
    "forfeit": false,
    "rescheduled": false
  }
]
```

Anomalies:
```json
[]
```

### TEAM1 team by id 1669

- Capability: `team.search`
- Status: `PASS`
- Query: `{
  "id": 1669,
  "name": null,
  "acronym": null,
  "page": 1,
  "limit": 20
}`
- Request: `{
  "path": "/dota2/teams",
  "params": {
    "page": 1,
    "per_page": 20,
    "filter[id]": 1669
  }
}`
- Raw summary: `{
  "item_count": 1,
  "item_types": {
    "dict": 1
  },
  "top_level_keys": [
    "acronym",
    "current_videogame",
    "dark_mode_image_url",
    "id",
    "image_url",
    "location",
    "modified_at",
    "name",
    "players",
    "slug"
  ],
  "role_values": [
    "4",
    "3",
    "2",
    "1",
    "5"
  ]
}`
- DTO item count: `1`
- Anomaly count: `0`

DTO sample:
```json
[
  {
    "id": 1669,
    "name": "Team Spirit",
    "acronym": "TS",
    "location": "RU",
    "slug": "team-spirit",
    "image_url": "https://cdn-api.pandascore.co/images/team/image/1669/153px_team_spirit_2022_lightmode.png",
    "current_roster": [
      {
        "id": 9419,
        "name": "MiLAN",
        "active": true,
        "role": [
          "soft_support"
        ],
        "first_name": "Milan",
        "last_name": "Kozomara",
        "nationality": "BA",
        "slug": "milan",
        "image_url": "https://cdn-api.pandascore.co/images/player/image/9419/600px-MiLAN_ESL_One_Genting_2018.jpg"
      },
      {
        "id": 26727,
        "name": "Collapse",
        "active": true,
        "role": [
          "offlane"
        ],
        "first_name": "Magomed",
        "last_name": "Khalilov",
        "nationality": "RU",
        "slug": "collapse",
        "image_url": "https://cdn-api.pandascore.co/images/player/image/26727/ezgif_7112cb82c5cd26f8.png"
      },
      {
        "id": 27480,
        "name": "Larl",
        "active": true,
        "role": [
          "mid"
        ],
        "first_name": "Denis",
        "last_name": "Sigitov",
        "nationality": "RU",
        "slug": "larl",
        "image_url": "https://cdn-api.pandascore.co/images/player/image/27480/900px_larl_2025_team_spirit.png"
      },
      {
        "id": 30258,
        "name": "Yatoro",
        "active": true,
        "role": [
          "carry"
        ],
        "first_name": "Ilya",
        "last_name": "Mulyarchuk",
        "nationality": "UA",
        "slug": "yatoro",
        "image_url": "https://cdn-api.pandascore.co/images/player/image/30258/ezgif_7a5a895029465e7b.png"
      },
      {
        "id": 49070,
        "name": "rue",
        "active": true,
        "role": [
          "hard_support"
        ],
        "first_name": "Aleksandr",
        "last_name": "Filin",
        "nationality": "RU",
        "slug": "rue",
        "image_url": "https://cdn-api.pandascore.co/images/player/image/49070/ezgif_7e0241e47149afc9.png"
      },
      {
        "id": 54351,
        "name": "not me",
        "active": true,
        "role": [
          "soft_support"
        ],
        "first_name": "Alexey",
        "last_name": "Kosmynin",
        "nationality": "RU",
        "slug": "notme",
        "image_url": null
      }
    ]
  }
]
```

Anomalies:
```json
[]
```

### TEAM2 team by name

- Capability: `team.search`
- Status: `PASS`
- Query: `{
  "id": null,
  "name": "Xtreme Gaming",
  "acronym": null,
  "page": 1,
  "limit": 20
}`
- Request: `{
  "path": "/dota2/teams",
  "params": {
    "page": 1,
    "per_page": 20,
    "search[name]": "Xtreme Gaming"
  }
}`
- Raw summary: `{
  "item_count": 1,
  "item_types": {
    "dict": 1
  },
  "top_level_keys": [
    "acronym",
    "current_videogame",
    "dark_mode_image_url",
    "id",
    "image_url",
    "location",
    "modified_at",
    "name",
    "players",
    "slug"
  ],
  "role_values": [
    "1"
  ]
}`
- DTO item count: `1`
- Anomaly count: `0`

DTO sample:
```json
[
  {
    "id": 128329,
    "name": "Xtreme Gaming",
    "acronym": "Xtreme",
    "location": "CN",
    "slug": "xtreme-gaming",
    "image_url": "https://cdn-api.pandascore.co/images/team/image/128329/t72899.png",
    "current_roster": [
      {
        "id": 9916,
        "name": "Ame",
        "active": true,
        "role": [
          "carry"
        ],
        "first_name": "Chunyu",
        "last_name": "Wang",
        "nationality": "CN",
        "slug": "ame",
        "image_url": "https://cdn-api.pandascore.co/images/player/image/9916/ame_lgd_removebg_preview.png"
      }
    ]
  }
]
```

Anomalies:
```json
[]
```

### P1 player by id 27480

- Capability: `player.search`
- Status: `PASS`
- Query: `{
  "id": 27480,
  "team_id": null,
  "name": null,
  "first_name": null,
  "last_name": null,
  "active": null,
  "page": 1,
  "limit": 20
}`
- Request: `{
  "path": "/dota2/players",
  "params": {
    "page": 1,
    "per_page": 20,
    "filter[id]": 27480
  }
}`
- Raw summary: `{
  "item_count": 1,
  "item_types": {
    "dict": 1
  },
  "top_level_keys": [
    "active",
    "current_team",
    "current_videogame",
    "first_name",
    "id",
    "image_url",
    "last_name",
    "modified_at",
    "name",
    "nationality",
    "role",
    "slug"
  ],
  "role_values": [
    "2"
  ]
}`
- DTO item count: `1`
- Anomaly count: `0`

DTO sample:
```json
[
  {
    "id": 27480,
    "name": "Larl",
    "active": true,
    "role": [
      "mid"
    ],
    "first_name": "Denis",
    "last_name": "Sigitov",
    "nationality": "RU",
    "slug": "larl",
    "image_url": "https://cdn-api.pandascore.co/images/player/image/27480/900px_larl_2025_team_spirit.png",
    "current_team": {
      "id": 1669,
      "name": "Team Spirit",
      "acronym": "TS",
      "location": "RU",
      "slug": "team-spirit",
      "image_url": "https://cdn-api.pandascore.co/images/team/image/1669/153px_team_spirit_2022_lightmode.png"
    }
  }
]
```

Anomalies:
```json
[]
```

### P2 player by id 28009

- Capability: `player.search`
- Status: `PASS`
- Query: `{
  "id": 28009,
  "team_id": null,
  "name": null,
  "first_name": null,
  "last_name": null,
  "active": null,
  "page": 1,
  "limit": 20
}`
- Request: `{
  "path": "/dota2/players",
  "params": {
    "page": 1,
    "per_page": 20,
    "filter[id]": 28009
  }
}`
- Raw summary: `{
  "item_count": 1,
  "item_types": {
    "dict": 1
  },
  "top_level_keys": [
    "active",
    "current_team",
    "current_videogame",
    "first_name",
    "id",
    "image_url",
    "last_name",
    "modified_at",
    "name",
    "nationality",
    "role",
    "slug"
  ],
  "role_values": [
    "3"
  ]
}`
- DTO item count: `1`
- Anomaly count: `0`

DTO sample:
```json
[
  {
    "id": 28009,
    "name": "TORONTOTOKYO",
    "active": true,
    "role": [
      "offlane"
    ],
    "first_name": "Alexander",
    "last_name": "Khertek",
    "nationality": "RU",
    "slug": "mlg-winner",
    "image_url": "https://cdn-api.pandascore.co/images/player/image/28009/600px_torontotokyo_2023_bet_boom_team.png",
    "current_team": {
      "id": 133882,
      "name": "Aurora",
      "acronym": "AUR",
      "location": "RS",
      "slug": "aurora-dota-2",
      "image_url": "https://cdn-api.pandascore.co/images/team/image/133882/600px_aurora_gaming_2025_allmode.png"
    }
  }
]
```

Anomalies:
```json
[]
```

### P3 active players for team 1669

- Capability: `player.search`
- Status: `PASS`
- Query: `{
  "id": null,
  "team_id": 1669,
  "name": null,
  "first_name": null,
  "last_name": null,
  "active": null,
  "page": 1,
  "limit": 10
}`
- Request: `{
  "path": "/dota2/players",
  "params": {
    "page": 1,
    "per_page": 10,
    "filter[team_id]": 1669
  }
}`
- Raw summary: `{
  "item_count": 6,
  "item_types": {
    "dict": 6
  },
  "top_level_keys": [
    "active",
    "current_team",
    "current_videogame",
    "first_name",
    "id",
    "image_url",
    "last_name",
    "modified_at",
    "name",
    "nationality",
    "role",
    "slug"
  ],
  "role_values": [
    "4",
    "5",
    "1",
    "2",
    "3"
  ]
}`
- DTO item count: `6`
- Anomaly count: `0`

DTO sample:
```json
[
  {
    "id": 54351,
    "name": "not me",
    "active": true,
    "role": [
      "soft_support"
    ],
    "first_name": "Alexey",
    "last_name": "Kosmynin",
    "nationality": "RU",
    "slug": "notme",
    "image_url": null,
    "current_team": {
      "id": 1669,
      "name": "Team Spirit",
      "acronym": "TS",
      "location": "RU",
      "slug": "team-spirit",
      "image_url": "https://cdn-api.pandascore.co/images/team/image/1669/153px_team_spirit_2022_lightmode.png"
    }
  },
  {
    "id": 49070,
    "name": "rue",
    "active": true,
    "role": [
      "hard_support"
    ],
    "first_name": "Aleksandr",
    "last_name": "Filin",
    "nationality": "RU",
    "slug": "rue",
    "image_url": "https://cdn-api.pandascore.co/images/player/image/49070/ezgif_7e0241e47149afc9.png",
    "current_team": {
      "id": 1669,
      "name": "Team Spirit",
      "acronym": "TS",
      "location": "RU",
      "slug": "team-spirit",
      "image_url": "https://cdn-api.pandascore.co/images/team/image/1669/153px_team_spirit_2022_lightmode.png"
    }
  }
]
```

Anomalies:
```json
[]
```

## Findings

### Confirmed contracts

- Requests are sent directly through `PandaScoreClient` and the corresponding
  adapter, without Agent/LLM/Tool Runtime involvement.
- DTO samples are serialized from the DotaMind SearchResult items.
- Normal missing data remains `None`/`[]`; local mapping anomalies remain visible
  in the SearchResult envelope.
- Real endpoint validation confirmed that `game.winner.id = null` is a normal
  representation of no game winner, especially for not-started games in
  canceled/forfeit or upcoming matches.
- The Match mapper now maps `winner.id=null` to `winner_id=None` without an
  anomaly while retaining anomalies for malformed winner relations.

### Provider anomalies observed

See the per-case anomaly blocks above. An empty list means no local mapping
anomaly was observed for that response.

### Contract mismatches requiring discussion

No `CONTRACT_REVIEW_REQUIRED` case was observed in this run. This validation
run does not modify DTOs or query schemas.
