"""Transient position transport. Never use read_source or return positions to tools."""

from datetime import UTC, datetime

from app.vnext.tools.errors import StructuredToolError

from .client import StratzError

POSITION_QUERY = """query HeatmapPositions($id: Long!) {
  match(id: $id) { id durationSeconds gameVersionId players {
    steamAccountId playerSlot heroId
    playbackData { playerUpdatePositionEvents { time x y } }
  } }
}"""


class StratzHeatmapAdapter:
    def __init__(self, client):
        self.client = client

    async def consume_positions(self, valve_game_id, consumer):
        payload = None
        try:
            payload = await self.client.graphql(POSITION_QUERY, {"id": valve_game_id})
            match = (payload.get("data") or {}).get("match")
            if (
                not isinstance(match, dict)
                or type(match.get("id")) is not int
                or match["id"] != valve_game_id
            ):
                raise StructuredToolError(
                    "provider_schema_error",
                    "Heatmap record identity unavailable",
                    {"provider": "stratz"},
                )
            # Only the supplied consumer sees this transient body; no source record/cache.
            return await consumer(match, datetime.now(UTC).isoformat())
        except StratzError:
            raise StructuredToolError(
                "provider_error", "STRATZ heatmap positions unavailable", {"provider": "stratz"}
            ) from None
        finally:
            if isinstance(payload, dict):
                payload.clear()
