# D2PT offline fixtures

These files are byte-for-byte copies of the raw D2PT JSON response bodies
observed by the WSL Ubuntu probe on 2026-09-27. They are source samples, not
synthetic data and not a production default cache.

| Fixture | Original request | Bytes | SHA-256 |
|---|---|---:|---|
| `pub_sven_pos1.json` | `https://dota2protracker.com/api/hero/18/builds?position=pos%201` | 43,825 | `b8785cba69b66593bd71c6776160493931fbc5748a546a8db2f615cf8d40762d` |
| `pro_sven.json` | `https://dota2protracker.com/api/hero/18/pro-builds` | 75,377 | `0f020e80155bf34c272047728ecdca63e115079f23b13cf9baa4fd8bb71ed738` |

The samples were fetched for Sven (`hero_id=18`), position 1. One hero and one
position do not establish that every hero/position has the same source shape.
The payload `updated_at` strings do not include an explicit timezone; the
fixtures preserve them without adding one.

The public JSON bodies were checked for credential-like fields before copying.
They contain public match/player data and no Cookie, Authorization value, API
key, or other credential. A separate user-provided report said a Guangzhou
container could reach D2PT. These fixtures came from the WSL probe above; they
were not retrieved from that container.
