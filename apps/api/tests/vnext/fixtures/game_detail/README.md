# OpenDota game-detail projection fixture

`opendota_9040460429.json` is the complete previously saved OpenDota response
for Valve game `9040460429`, reused from the local Dota Lens/OpenDota comparison.
The source endpoint is `https://api.opendota.com/api/matches/9040460429`.
This is a historical response, not a fresh availability check; the game start
time must not be interpreted as its retrieval time. Formatting is normalized
for review, without removing source fields.

Tests read it locally and make no provider or model requests. Keeping excluded
fields in the source fixture also exercises the boundary: source extensions,
chat, benchmarks, and detailed target maps must not escape into the closed DTO.
