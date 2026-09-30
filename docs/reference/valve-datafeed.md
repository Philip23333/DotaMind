# Valve Dota datafeed observations

This note records eight bounded real requests made during an earlier Valve
datafeed probe. Endpoint names, query examples, and response nesting below come
from that probe's request manifest and response summaries. This document does
not depend on the temporary probe directory and intentionally omits the raw
payloads.

## Observed endpoints

| Endpoint | Example query | Observed response location | Observed use |
|---|---|---|---|
| `patchnoteslist` | `language=english` | Root `patches` | Lists patch records; the probe used it to identify the latest patch entry. |
| `herolist` | `language=english` | `result.data.heroes` | Lists hero identities and display fields. The sampled response contained 127 heroes. |
| `abilitylist` | `language=english` | `result.data.itemabilities` | Lists ability and talent identities with summary fields. The sample included ID 0 (`dota_base_ability`); the response contained 2,702 rows. |
| `itemlist` | `language=english` | `result.data.itemabilities` | Lists item identities and summary fields, including `recipes` where present. The sample contained 544 rows. |
| `herodata` | `hero_id=18&language=english` | `result.data.heroes` | Returns one sampled hero detail record with attributes, abilities, talents, facets, and other hero fields. |
| `abilitydata` | `ability_id=673&language=english` | `result.data.abilities` | Returns one sampled ability/talent detail record with description and value fields. |
| `itemdata` | `item_id=1&language=english` | `result.data.items` | Returns one sampled item detail record with description and value fields. |
| `patchnotes` | `version=7.41f&language=english` | Root fields `patch_number`, `patch_name`, `patch_timestamp`, `items`, `neutral_items`, `heroes`, and `success` | Returns one sampled patch-note document. |

## Findings from the samples

- At probe time, `patchnoteslist` identified `7.41f` as the latest patch. This
  is a dated observation, not a permanent statement about the latest version.
- The sampled Sven record (`hero_id=18`) contained five abilities and eight
  talents. Its talent IDs also appeared in the sampled ability list, and
  `abilitydata(ability_id=673)` returned a detailed `special_bonus` record.
- The sampled `itemlist` records included recipe relationships; the probe found
  125 records with a non-empty `recipes` field. `itemdata` supplied richer detail such as
  descriptions and value arrays for the sampled item.
- The sampled entity list/detail responses did not expose a patch revision field
  that guarantees entity contents remain unchanged for the lifetime of a patch.
  A same-patch full-fetch skip is therefore DotaMind's update policy, not a
  Valve immutability guarantee.

The eight requests used English query parameters. They do not establish complete
Chinese localization, every hero's detail shape, all item/ability edge cases, or
the correctness of full-catalog normalization. The sample is evidence for these
observed structures only; it is not whole-source coverage or an update
acceptance result.
