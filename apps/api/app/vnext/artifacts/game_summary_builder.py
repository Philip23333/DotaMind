"""Build a canonical game-summary artifact from provider-neutral construction input."""

from app.vnext.artifacts.game_summary import (
    CatalogValue,
    Draft,
    DraftEvent,
    GameInfo,
    GameSummaryArtifact,
    ItemSlot,
    PlayerGameSummary,
    PlayerIdentity,
    PlayerItems,
    Teams,
    TeamSummary,
)
from app.vnext.domain.construction import GameConstructionContext, PlayerContext
from app.vnext.domain.refs import ItemSlotRef
from app.vnext.identity import AbilityResolver, HeroResolver, ItemResolver


class MissingValveMatchIdError(ValueError):
    """Raised when construction input cannot identify a canonical game."""


class GameSummaryBuilder:
    """Convert construction context into the canonical schema version 2."""

    def __init__(
        self,
        hero_resolver: HeroResolver,
        item_resolver: ItemResolver,
        ability_resolver: AbilityResolver,
    ) -> None:
        self._hero_resolver = hero_resolver
        self._item_resolver = item_resolver
        self._ability_resolver = ability_resolver

    def build(self, context: GameConstructionContext) -> GameSummaryArtifact:
        valve_match_id = context.game.valve_match_id
        if valve_match_id is None:
            raise MissingValveMatchIdError("cannot build a game summary without valve_match_id")

        picks, bans = self._draft(context)
        return GameSummaryArtifact(
            game=GameInfo(
                valve_match_id=valve_match_id,
                start_time=context.game.start_time,
                duration_seconds=context.game.duration_seconds,
                winner=self._winner(context.game.radiant_win),
                game_mode=CatalogValue(id=context.game.game_mode_id, name=None),
                lobby_type=CatalogValue(id=context.game.lobby_type_id, name=None),
            ),
            teams=Teams(
                radiant=TeamSummary(
                    valve_team_id=context.radiant_team.team_ref.valve_team_id,
                    name=context.radiant_team.name,
                    score=context.radiant_team.score,
                ),
                dire=TeamSummary(
                    valve_team_id=context.dire_team.team_ref.valve_team_id,
                    name=context.dire_team.name,
                    score=context.dire_team.score,
                ),
            ),
            players=[
                self._player(player)
                for player in context.players
                if player.hero_ref is not None
            ],
            draft=Draft(picks=picks, bans=bans),
        )

    @staticmethod
    def _winner(radiant_win: bool | None) -> str | None:
        if radiant_win is None:
            return None
        return "radiant" if radiant_win else "dire"

    def _player(self, context: PlayerContext) -> PlayerGameSummary:
        hero_ref = context.hero_ref
        if hero_ref is None:
            raise ValueError("player contexts without hero_ref must be omitted before construction")
        return PlayerGameSummary(
            identity=PlayerIdentity(
                steam_account_id=context.player_ref.steam_account_id,
                registered_name=context.registered_name,
                persona_name=context.persona_name,
            ),
            side=context.side,
            player_slot=context.player_slot,
            hero=self._hero_resolver.resolve(hero_ref),
            items=PlayerItems(
                inventory=[self._item_slot(slot) for slot in context.item_slots],
                backpack=[self._item_slot(slot) for slot in context.backpack_slots],
                neutral_items=[
                    self._item_resolver.resolve(slot.item)
                    for slot in context.neutral_items
                    if slot.item is not None
                ],
            ),
            ability_upgrades=[
                self._ability_resolver.resolve(upgrade)
                for upgrade in context.ability_upgrades
            ],
        )

    def _draft(self, context: GameConstructionContext) -> tuple[list[DraftEvent], list[DraftEvent]]:
        picks: list[DraftEvent] = []
        bans: list[DraftEvent] = []
        for event in context.draft_events:
            draft_event = DraftEvent(
                order=event.order,
                side=event.side,
                hero_id=event.hero.valve_hero_id,
                hero_name=self._hero_resolver.resolve(event.hero).name,
            )
            (picks if event.is_pick else bans).append(draft_event)
        return picks, bans

    def _item_slot(self, source: ItemSlotRef) -> ItemSlot:
        if source.item is None:
            return ItemSlot(slot=source.slot, id=None, name=None)
        item = self._item_resolver.resolve(source.item)
        return ItemSlot(slot=source.slot, id=item.id, name=item.name)

__all__ = ["GameSummaryBuilder", "MissingValveMatchIdError"]
