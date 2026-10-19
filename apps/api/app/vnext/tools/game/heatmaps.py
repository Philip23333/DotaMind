"""One semantic entry for explicitly requested cumulative heatmap images."""

from app.vnext.capabilities.game.heatmap_models import HeatmapInput, HeatmapResult
from app.vnext.tools.definition import ToolDefinition


def register_game_heatmaps_tool(registry, service):
    registry.register(
        ToolDefinition(
            name="game.heatmaps",
            description=(
                "Only when the user requests player heatmaps, start/inspect a background batch "
                "by canonical Valve ID. action=get reuses a batch; avoid repeated polling. "
                "action=retry regenerates a finished batch; action=cancel stops it. Returns "
                "paginated 256x256 images for cumulative 0-5/10/15... minute and final windows, "
                "with status and provenance. Raw positions are never returned or retained. "
                "Colours show sample density, not dwell time; dead heroes may be included. "
                "If a verified map is unavailable, report that limitation; do not invent images. "
                "Ordinary game.detail does not wait for images. Use offset/limit for pages. "
                "Reuse returned image_ref unchanged; never construct references."
            ),
            input_model=HeatmapInput,
            output_model=HeatmapResult,
            handler=service.get,
            read_only=True,
            parallel_safe=True,
            metadata={"game": "dota2", "domain": "game", "provider": "stratz"},
        )
    )
