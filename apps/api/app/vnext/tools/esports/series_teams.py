"""Model-facing series participant-team tool backed by a semantic callable."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.vnext.capabilities.esports.series import SeriesTeamsInput, SeriesTeamsResult
from app.vnext.tools.definition import ToolDefinition
from app.vnext.tools.registry import ToolRegistry

SeriesTeamsHandler = Callable[[SeriesTeamsInput], Awaitable[SeriesTeamsResult]]

SERIES_TEAMS_DESCRIPTION = """\
List teams participating in one known Dota 2 series.

Use series_id from esports.series.search.

This returns the participating team list for that series.
"""


def register_series_teams_tool(
    registry: ToolRegistry,
    teams: SeriesTeamsHandler,
) -> None:
    async def handler(args: SeriesTeamsInput) -> SeriesTeamsResult:
        return await teams(args)

    registry.register(
        ToolDefinition(
            name="esports.series.teams",
            description=SERIES_TEAMS_DESCRIPTION,
            input_model=SeriesTeamsInput,
            output_model=SeriesTeamsResult,
            handler=handler,
            read_only=True,
            parallel_safe=True,
            metadata={"game": "dota2", "domain": "series"},
        )
    )


__all__ = [
    "SERIES_TEAMS_DESCRIPTION",
    "SeriesTeamsHandler",
    "register_series_teams_tool",
]
