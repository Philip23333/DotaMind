"""Build a version 5 game-summary artifact from construction input."""

from app.vnext.domain.construction import GameConstructionContext

from .game_summary_builder_v4 import GameSummaryBuilderV4
from .game_summary_v5 import (
    EventLeague,
    EventMatch,
    EventSeries,
    EventTournament,
    GameEvent,
    GameSummaryArtifactV5,
)


class GameSummaryBuilderV5(GameSummaryBuilderV4):
    """Reuse V4 canonical game facts and add only event context."""

    def build(self, context: GameConstructionContext) -> GameSummaryArtifactV5:
        v4 = super().build(context)
        source = context.event
        return GameSummaryArtifactV5(
            event=GameEvent(
                league=EventLeague(name=source.league_name if source else None),
                series=EventSeries(
                    name=source.series_name if source else None,
                    year=source.series_year if source else None,
                    season=source.series_season if source else None,
                ),
                tournament=EventTournament(name=source.tournament_name if source else None),
                match=EventMatch(
                    name=source.match_name if source else None,
                    number_of_games=source.match_number_of_games if source else None,
                    match_type=source.match_type if source else None,
                ),
                game_position=source.game_position if source else None,
            ),
            game=v4.game,
            teams=v4.teams,
            players=v4.players,
            draft=v4.draft,
        )


__all__ = ["GameSummaryBuilderV5"]
