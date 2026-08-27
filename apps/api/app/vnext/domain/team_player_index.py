"""Internal PandaScore identity mappings shared by team and player services."""

from __future__ import annotations

from app.vnext.domain.common.models import PlayerRef, TeamRef, hash_ref


class TeamPlayerRefIndex:
    """Map opaque model-facing refs to PandaScore IDs within one runtime."""

    def __init__(self) -> None:
        self._team_provider_ids: dict[str, int] = {}
        self._player_provider_ids: dict[str, int] = {}

    def remember_team(self, provider_id: int) -> TeamRef:
        ref = TeamRef(value=hash_ref("team", "pandascore", provider_id))
        self._team_provider_ids[ref.value] = provider_id
        return ref

    def remember_player(self, provider_id: int) -> PlayerRef:
        ref = PlayerRef(value=hash_ref("player", "pandascore", provider_id))
        self._player_provider_ids[ref.value] = provider_id
        return ref

    def team_provider_id(self, ref: TeamRef) -> int | None:
        return self._team_provider_ids.get(ref.value)

    def player_provider_id(self, ref: PlayerRef) -> int | None:
        return self._player_provider_ids.get(ref.value)


__all__ = ["TeamPlayerRefIndex"]
