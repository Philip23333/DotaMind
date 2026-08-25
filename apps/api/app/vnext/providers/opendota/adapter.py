"""HTTP-only OpenDota adapter for the Phase 2 resolution boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import ValidationError

from app.vnext.domain.construction import (
    GameConstructionContext,
    GameContext,
    PlayerContext,
    TeamContext,
)
from app.vnext.domain.refs import (
    AbilityUpgradeRef,
    DraftEventRef,
    HeroRef,
    ItemRef,
    ItemSlotRef,
    PlayerRef,
    TeamRef,
)
from app.vnext.providers.common import ProviderBatch, ProviderObject
from app.vnext.providers.opendota.models import (
    OpenDotaGameConstructionMatch,
    OpenDotaGameConstructionPlayer,
    OpenDotaGameConstructionTeam,
    OpenDotaLeague,
    OpenDotaLeagueMatch,
    OpenDotaMatchDetail,
    OpenDotaTeam,
)


class OpenDotaProviderError(RuntimeError):
    """Base class for sanitized OpenDota adapter failures."""


class OpenDotaConfigurationError(OpenDotaProviderError):
    """The adapter configuration is invalid."""


class OpenDotaTimeoutError(OpenDotaProviderError):
    """OpenDota did not respond before the configured timeout."""


class OpenDotaHTTPError(OpenDotaProviderError):
    """OpenDota returned an unsuccessful HTTP response."""

    def __init__(self, status_code: int, path: str) -> None:
        self.status_code = status_code
        self.path = path
        super().__init__(f"OpenDota request returned HTTP {status_code}")


class OpenDotaSchemaError(OpenDotaProviderError):
    """OpenDota returned a payload outside the adapter contract."""


class OpenDotaGameConstructionAdapter:
    """Pure OpenDota-to-construction mapping with no transport behavior."""

    def to_construction_context(
        self,
        source: OpenDotaGameConstructionMatch,
    ) -> GameConstructionContext:
        return GameConstructionContext(
            game=GameContext(
                valve_match_id=source.match_id,
                start_time=(
                    datetime.fromtimestamp(source.start_time, tz=timezone.utc)
                    if source.start_time is not None
                    else None
                ),
                duration_seconds=source.duration,
                radiant_win=source.radiant_win,
                game_mode_id=source.game_mode,
                lobby_type_id=source.lobby_type,
            ),
            radiant_team=self._team_context(source.radiant_team, source.radiant_score),
            dire_team=self._team_context(source.dire_team, source.dire_score),
            players=[self._player_context(player) for player in source.players],
            draft_events=[
                DraftEventRef(
                    order=event.order,
                    side="radiant" if event.team == 0 else "dire",
                    hero=HeroRef(valve_hero_id=event.hero_id),
                    is_pick=event.is_pick,
                )
                for event in source.picks_bans
            ],
        )

    @staticmethod
    def _team_context(
        source: OpenDotaGameConstructionTeam | None,
        score: int | None,
    ) -> TeamContext:
        return TeamContext(
            team_ref=TeamRef(valve_team_id=source.valve_team_id if source else None),
            name=source.name if source else None,
            score=score,
        )

    @classmethod
    def _player_context(cls, source: OpenDotaGameConstructionPlayer) -> PlayerContext:
        return PlayerContext(
            player_ref=PlayerRef(steam_account_id=source.account_id),
            registered_name=source.registered_name,
            persona_name=source.persona_name,
            side="radiant" if source.player_slot < 128 else "dire",
            player_slot=source.player_slot,
            hero_ref=HeroRef(valve_hero_id=source.hero_id) if source.hero_id is not None else None,
            item_slots=[
                cls._item_slot(slot, item_id)
                for slot, item_id in enumerate(
                    (
                        source.item_0,
                        source.item_1,
                        source.item_2,
                        source.item_3,
                        source.item_4,
                        source.item_5,
                    )
                )
            ],
            backpack_slots=[
                cls._item_slot(slot, item_id)
                for slot, item_id in enumerate(
                    (source.backpack_0, source.backpack_1, source.backpack_2),
                    start=6,
                )
            ],
            neutral_items=[
                cls._item_slot(slot, item_id)
                for slot, item_id in enumerate(
                    (source.item_neutral, source.item_neutral2),
                )
            ],
            ability_upgrades=[
                AbilityUpgradeRef(
                    valve_ability_id=upgrade.ability_id,
                    level=upgrade.level,
                    time_seconds=upgrade.time_seconds,
                )
                for upgrade in source.ability_upgrades
                if (
                    upgrade.ability_id is not None
                    and upgrade.level is not None
                    and upgrade.time_seconds is not None
                )
            ],
        )

    @staticmethod
    def _item_slot(slot: int, item_id: int | None) -> ItemSlotRef:
        return ItemSlotRef(
            slot=slot,
            item=ItemRef(valve_item_id=item_id) if item_id not in (None, 0) else None,
        )


class OpenDotaAdapter:
    """Minimal OpenDota client used only below the domain tool boundary."""

    def __init__(
        self,
        base_url: str = "https://api.opendota.com/api",
        api_key: str | None = None,
        *,
        request_timeout_seconds: float = 20.0,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if client is not None and transport is not None:
            raise ValueError("provide either client or transport, not both")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip() if isinstance(api_key, str) and api_key.strip() else None
        self.request_timeout_seconds = request_timeout_seconds
        self._client = client
        self._transport = transport
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
        self._client = None if self._owns_client else self._client

    async def list_leagues(self) -> ProviderBatch[OpenDotaLeague]:
        path = "/leagues"
        payload, fetched_at = await self._get_json(path)
        rows = self._require_list(payload, path)
        return ProviderBatch(
            items=[self._parse(OpenDotaLeague, row, path) for row in rows],
            fetched_at=fetched_at,
        )

    async def search_leagues(self, query: str | None = None) -> ProviderBatch[OpenDotaLeague]:
        """Return the league catalog; name matching stays in the domain layer."""

        return await self.list_leagues()

    async def list_teams(self) -> ProviderBatch[OpenDotaTeam]:
        path = "/teams"
        payload, fetched_at = await self._get_json(path)
        rows = self._require_list(payload, path)
        return ProviderBatch(
            items=[self._parse(OpenDotaTeam, row, path) for row in rows],
            fetched_at=fetched_at,
        )

    async def list_league_teams(self, league_id: int) -> ProviderBatch[OpenDotaTeam]:
        path = f"/leagues/{league_id}/teams"
        payload, fetched_at = await self._get_json(path)
        rows = self._require_list(payload, path)
        return ProviderBatch(
            items=[self._parse(OpenDotaTeam, row, path) for row in rows],
            fetched_at=fetched_at,
        )

    async def list_league_matches(
        self,
        league_id: int,
    ) -> ProviderBatch[OpenDotaLeagueMatch]:
        path = f"/leagues/{league_id}/matches"
        payload, fetched_at = await self._get_json(path)
        rows = self._require_list(payload, path)
        items: list[OpenDotaLeagueMatch] = []
        for row in rows:
            item = self._parse(OpenDotaLeagueMatch, row, path)
            if item.league_id is None:
                item = item.model_copy(update={"league_id": league_id})
            items.append(item)
        return ProviderBatch(items=items, fetched_at=fetched_at)

    async def get_match_detail(
        self,
        match_id: int,
    ) -> ProviderObject[OpenDotaMatchDetail]:
        path = f"/matches/{match_id}"
        payload, fetched_at = await self._get_json(path)
        if not isinstance(payload, dict):
            raise OpenDotaSchemaError(f"OpenDota response at {path} must be an object")
        return ProviderObject(
            item=self._parse(OpenDotaMatchDetail, payload, path),
            fetched_at=fetched_at,
        )

    async def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> tuple[Any, datetime]:
        client = self._client_for_request()
        request_params = dict(params or {})
        if self.api_key:
            request_params["api_key"] = self.api_key
        try:
            response = await client.get(
                path,
                params=request_params or None,
                headers={"Accept": "application/json"},
            )
        except httpx.TimeoutException as exc:
            raise OpenDotaTimeoutError("OpenDota request timed out") from exc
        except httpx.HTTPError as exc:
            raise OpenDotaProviderError("OpenDota request failed") from exc
        if response.status_code >= 400:
            raise OpenDotaHTTPError(response.status_code, path)
        try:
            payload = response.json()
        except ValueError as exc:
            raise OpenDotaSchemaError("OpenDota response was not valid JSON") from exc
        return payload, datetime.now(timezone.utc)

    def _client_for_request(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.request_timeout_seconds,
                transport=self._transport,
            )
        return self._client

    @staticmethod
    def _require_list(payload: Any, path: str) -> list[Any]:
        if not isinstance(payload, list):
            raise OpenDotaSchemaError(f"OpenDota response at {path} must be a list")
        return payload

    @staticmethod
    def _parse(model: type[Any], payload: Any, path: str) -> Any:
        try:
            return model.model_validate(payload)
        except (ValidationError, TypeError, ValueError) as exc:
            raise OpenDotaSchemaError(f"OpenDota response at {path} was invalid") from exc


__all__ = [
    "OpenDotaAdapter",
    "OpenDotaConfigurationError",
    "OpenDotaGameConstructionAdapter",
    "OpenDotaHTTPError",
    "OpenDotaProviderError",
    "OpenDotaSchemaError",
    "OpenDotaTimeoutError",
]
