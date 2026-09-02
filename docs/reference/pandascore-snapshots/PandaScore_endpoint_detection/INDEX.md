# PandaScore Dota 2 endpoint detection index

Scope is deliberately limited to the 16 user-selected Dota 2 reference endpoints. Each linked file is endpoint-local evidence extracted from PandaScore’s official `.md` reference page; no cross-endpoint abstraction is applied.

| # | Resource | Endpoint | File | Explicitly available to all customers | Official reference |
| --- | --- | --- | --- | --- | --- |
| 1 | leagues | `GET /dota2/leagues` | [01-get_dota2_leagues.md](01-get_dota2_leagues.md) | Yes | [reference](https://developers.pandascore.co/reference/get_dota2_leagues.md) |
| 2 | matches | `GET /dota2/matches` | [02-get_dota2_matches.md](02-get_dota2_matches.md) | Yes | [reference](https://developers.pandascore.co/reference/get_dota2_matches.md) |
| 3 | matches | `GET /dota2/matches/past` | [03-get_dota2_matches_past.md](03-get_dota2_matches_past.md) | Yes | [reference](https://developers.pandascore.co/reference/get_dota2_matches_past.md) |
| 4 | matches | `GET /dota2/matches/running` | [04-get_dota2_matches_running.md](04-get_dota2_matches_running.md) | Yes | [reference](https://developers.pandascore.co/reference/get_dota2_matches_running.md) |
| 5 | matches | `GET /dota2/matches/upcoming` | [05-get_dota2_matches_upcoming.md](05-get_dota2_matches_upcoming.md) | Yes | [reference](https://developers.pandascore.co/reference/get_dota2_matches_upcoming.md) |
| 6 | players | `GET /dota2/players` | [06-get_dota2_players.md](06-get_dota2_players.md) | Yes | [reference](https://developers.pandascore.co/reference/get_dota2_players.md) |
| 7 | series | `GET /dota2/series` | [07-get_dota2_series.md](07-get_dota2_series.md) | Yes | [reference](https://developers.pandascore.co/reference/get_dota2_series.md) |
| 8 | series | `GET /dota2/series/past` | [08-get_dota2_series_past.md](08-get_dota2_series_past.md) | Yes | [reference](https://developers.pandascore.co/reference/get_dota2_series_past.md) |
| 9 | series | `GET /dota2/series/running` | [09-get_dota2_series_running.md](09-get_dota2_series_running.md) | Yes | [reference](https://developers.pandascore.co/reference/get_dota2_series_running.md) |
| 10 | series | `GET /dota2/series/upcoming` | [10-get_dota2_series_upcoming.md](10-get_dota2_series_upcoming.md) | Yes | [reference](https://developers.pandascore.co/reference/get_dota2_series_upcoming.md) |
| 11 | teams | `GET /dota2/series/{serie_id_or_slug}/teams` | [11-get_dota2_series_serieidorslug_teams.md](11-get_dota2_series_serieidorslug_teams.md) | Yes | [reference](https://developers.pandascore.co/reference/get_dota2_series_serieidorslug_teams.md) |
| 12 | teams | `GET /dota2/teams` | [12-get_dota2_teams.md](12-get_dota2_teams.md) | Yes | [reference](https://developers.pandascore.co/reference/get_dota2_teams.md) |
| 13 | tournaments | `GET /dota2/tournaments` | [13-get_dota2_tournaments.md](13-get_dota2_tournaments.md) | Yes | [reference](https://developers.pandascore.co/reference/get_dota2_tournaments.md) |
| 14 | tournaments | `GET /dota2/tournaments/past` | [14-get_dota2_tournaments_past.md](14-get_dota2_tournaments_past.md) | Yes | [reference](https://developers.pandascore.co/reference/get_dota2_tournaments_past.md) |
| 15 | tournaments | `GET /dota2/tournaments/running` | [15-get_dota2_tournaments_running.md](15-get_dota2_tournaments_running.md) | Yes | [reference](https://developers.pandascore.co/reference/get_dota2_tournaments_running.md) |
| 16 | tournaments | `GET /dota2/tournaments/upcoming` | [16-get_dota2_tournaments_upcoming.md](16-get_dota2_tournaments_upcoming.md) | Yes | [reference](https://developers.pandascore.co/reference/get_dota2_tournaments_upcoming.md) |

Collected at: 2026-09-02T10:37:58.061776Z
