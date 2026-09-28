# D2PT offline fixtures

The original Sven files are byte-for-byte copies of raw D2PT JSON response
bodies observed by the WSL Ubuntu probe on 2026-09-27. The three additional Pro
files below were captured by a bounded WSL parser diagnosis on 2026-09-28. They
are source samples, not synthetic data and not a production default cache.

| Fixture | Original request | Bytes | SHA-256 |
|---|---|---:|---|
| `pub_sven_pos1.json` | `https://dota2protracker.com/api/hero/18/builds?position=pos%201` | 43,825 | `b8785cba69b66593bd71c6776160493931fbc5748a546a8db2f615cf8d40762d` |
| `pro_sven.json` | `https://dota2protracker.com/api/hero/18/pro-builds` | 75,377 | `0f020e80155bf34c272047728ecdca63e115079f23b13cf9baa4fd8bb71ed738` |

The samples were fetched for Sven (`hero_id=18`), position 1. One hero and one
position do not establish that every hero/position has the same source shape.
The payload `updated_at` strings do not include an explicit timezone; the
fixtures preserve them without adding one.

All five public JSON bodies were checked for credential-like fields. They
contain public match/player data and no Cookie, Authorization value, API key,
request headers, or other credential. A separate user-provided report said a
Guangzhou container could reach D2PT. These fixtures came from WSL probes; they
were not retrieved from that container.

## Pro ability-ID diagnosis samples

These three raw Pro responses reproduced the parser's `ability_id=0` failure.
The values and event counts are source observations; they do not establish what
ID zero means in game data. The relevant parser regression uses every match and
ability event in each body.

| Fixture | Hero ID | Original request | Captured UTC (`retrieved_at`) | Bytes | SHA-256 | Recent matches | Ability events | Zero-ID events |
|---|---:|---|---|---:|---|---:|---:|---:|
| `pro_antimage.json` | 1 | `https://dota2protracker.com/api/hero/1/pro-builds` | `2026-09-28T10:06:10.687937+00:00` | 57,211 | `f5f6e34f7fe5e0807fbdb26dc7a93e7c6500b7a9ca05570eea8b955a512e5670` | 5 | 141 | 7 |
| `pro_axe.json` | 2 | `https://dota2protracker.com/api/hero/2/pro-builds` | `2026-09-28T10:06:13.377255+00:00` | 162,415 | `d144cc678c13b99bac76df13f2988545758060f8049c24f0fa694ad990d7ef4f` | 16 | 354 | 67 |
| `pro_crystal_maiden.json` | 5 | `https://dota2protracker.com/api/hero/5/pro-builds` | `2026-09-28T10:06:15.907202+00:00` | 59,707 | `a3c562fde86546a33c234b4d6cfbdd72e2f10275f73d0b77b5dad1fbcfd44485` | 5 | 116 | 9 |
