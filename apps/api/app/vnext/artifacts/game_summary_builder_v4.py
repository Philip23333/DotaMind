"""Build a version 4 game-summary artifact from construction input."""

from app.vnext.domain.construction import GameConstructionContext, PlayerContext
from app.vnext.domain.refs import ItemSlotRef
from app.vnext.identity.ability_v4 import AbilityResolverV4
from app.vnext.identity.hero_v4 import HeroResolverV4
from app.vnext.identity.item_v4 import ItemResolverV4

from .game_summary_builder import MissingValveMatchIdError
from .game_summary_v4 import (
    CatalogValue,
    Draft,
    DraftEvent,
    GameInfo,
    GameSummaryArtifactV4,
    ItemSlot,
    PlayerEconomy,
    PlayerGameSummary,
    PlayerIdentity,
    PlayerItems,
    PlayerStats,
    PurchaseEvent,
    Teams,
    TeamSummary,
)


class GameSummaryBuilderV4:
    """Convert construction context into the canonical schema version 4."""

    def __init__(
        self,
        hero_resolver: HeroResolverV4,
        item_resolver: ItemResolverV4,
        ability_resolver: AbilityResolverV4,
    ) -> None:
        self._hero_resolver = hero_resolver
        self._item_resolver = item_resolver
        self._ability_resolver = ability_resolver

    def build(self, context: GameConstructionContext) -> GameSummaryArtifactV4:
        valve_match_id = context.game.valve_match_id
        if valve_match_id is None:
            raise MissingValveMatchIdError("cannot build a game summary without valve_match_id")

        picks, bans = self._draft(context)
        return GameSummaryArtifactV4(
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
            stats=PlayerStats(
                level=context.level,
                kills=context.kills,
                deaths=context.deaths,
                assists=context.assists,
                last_hits=context.last_hits,
                denies=context.denies,
            ),
            economy=PlayerEconomy(
                net_worth=context.net_worth,
                gold_per_min=context.gold_per_min,
                xp_per_min=context.xp_per_min,
            ),
            items=PlayerItems(
                inventory=[self._item_slot(slot) for slot in context.item_slots],
                backpack=[self._item_slot(slot) for slot in context.backpack_slots],
                neutral_items=(
                    [self._item_slot(slot) for slot in context.neutral_items]
                    if context.neutral_items
                    else [ItemSlot(slot=0), ItemSlot(slot=1)]
                ),
            ),
            purchase_history=self._purchase_history(context),
            ability_upgrades=[
                self._ability_resolver.resolve(upgrade)
                for upgrade in context.ability_upgrades
            ],
        )

    def _draft(self, context: GameConstructionContext) -> tuple[list[DraftEvent], list[DraftEvent]]:
        picks: list[DraftEvent] = []
        bans: list[DraftEvent] = []
        for event in context.draft_events:
            hero = self._hero_resolver.resolve(event.hero)
            draft_event = DraftEvent(
                order=event.order,
                side=event.side,
                hero_id=hero.id,
                hero_name_en=hero.name_en,
                hero_name_zh=hero.name_zh,
            )
            (picks if event.is_pick else bans).append(draft_event)
        return picks, bans

    def _item_slot(self, source: ItemSlotRef) -> ItemSlot:
        if source.item is None:
            return ItemSlot(slot=source.slot)
        item = self._item_resolver.resolve(source.item)
        return ItemSlot(
            slot=source.slot,
            id=item.id,
            name_en=item.name_en,
            name_zh=item.name_zh,
        )

    def _purchase_history(self, context: PlayerContext) -> list[PurchaseEvent]:
        events: list[PurchaseEvent] = []
        for source in context.purchase_history:
            item = self._item_resolver.resolve_key(source.item_key)
            if item is None:
                continue
            events.append(
                PurchaseEvent(
                    time_seconds=source.time_seconds,
                    item_id=item.id,
                    item_name_en=item.name_en,
                    item_name_zh=item.name_zh,
                )
            )
        return events


__all__ = ["GameSummaryBuilderV4"]
