"""Read validated STRATZ match facts without coupling transport to the public DTO."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictInt,
    ValidationError,
    field_validator,
)

from app.vnext.providers.source_reads import read_source
from app.vnext.tools.errors import StructuredToolError

from .client import (
    StratzGraphQLClient,
    StratzGraphQLError,
    StratzHTTPError,
    StratzResponseError,
    StratzTimeoutError,
    StratzTransportError,
)

GAME_DETAIL_QUERY = """\
query GameDetail($id: Long!) {
  match(id: $id) {
    id startDateTime durationSeconds didRadiantWin gameVersionId firstBloodTime
    radiantTeamId direTeamId radiantKills direKills
    radiantTeam { id name } direTeam { id name }
    pickBans { order isPick heroId bannedHeroId isRadiant }
    chatEvents { time type fromHeroId toHeroId value isRadiant }
    players {
      steamAccountId playerSlot heroId isRadiant
      kills deaths assists level numLastHits numDenies heroDamage towerDamage heroHealing networth
      goldPerMinute experiencePerMinute
      item0Id item1Id item2Id item3Id item4Id item5Id
      backpack0Id backpack1Id backpack2Id neutral0Id
      stats {
        itemPurchases { time itemId }
        matchPlayerBuffEvent { time itemId abilityId stackCount }
        heroDamageReport { dealtTargets { target amount } }
      }
      playbackData {
        goldEvents { time amount reason isValidForStats }
        deathEvents { time attacker target goldFed goldLost timeDead }
        buyBackEvents { time }
        abilityLearnEvents { time abilityId level levelObtained isTalent isUltimate }
        playerUpdateLevelEvents { time level }
        inventoryEvents {
          time
          item0 { itemId charges } item1 { itemId charges } item2 { itemId charges }
          item3 { itemId charges } item4 { itemId charges } item5 { itemId charges }
          backPack0 { itemId charges } backPack1 { itemId charges } backPack2 { itemId charges }
          neutral0 { itemId charges }
        }
      }
    }
  }
}
"""


class StratzGameRecord(BaseModel):
    """Internal source document; never an Artifact handle for the original response."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    match_id: StrictInt = Field(gt=0)
    provider: Literal["stratz"] = "stratz"
    retrieved_at: datetime
    data: dict[str, JsonValue]
    field_issues: list[str] = Field(default_factory=list)

    @field_validator("retrieved_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return value


class StratzGameDetailAdapter:
    def __init__(self, client: StratzGraphQLClient) -> None:
        self.client = client

    async def get_game_record(self, match_id: int) -> StratzGameRecord:
        if type(match_id) is not int or match_id <= 0:
            raise ValueError("match_id must be a positive integer")
        return await read_source(self, "game_detail", match_id, lambda: self._read(match_id))

    async def _read(self, match_id: int) -> StratzGameRecord:
        try:
            payload = await self.client.graphql(
                GAME_DETAIL_QUERY, {"id": match_id}, allow_partial_data=True
            )
        except StratzTimeoutError:
            raise StructuredToolError(
                "provider_timeout", "STRATZ game detail timed out", {"provider": "stratz"}
            ) from None
        except StratzHTTPError as exc:
            raise StructuredToolError(
                "provider_http_error",
                "STRATZ game detail request failed",
                {"provider": "stratz", "status_code": exc.status_code},
            ) from None
        except StratzResponseError as exc:
            raise _schema_error(exc.path) from None
        except (StratzGraphQLError, StratzTransportError):
            raise StructuredToolError(
                "provider_error", "STRATZ game detail request failed", {"provider": "stratz"}
            ) from None
        data = payload.get("data")
        if not isinstance(data, dict) or "match" not in data:
            raise _schema_error("data.match")
        match = data["match"]
        if match is None:
            raise StructuredToolError(
                "provider_error",
                "STRATZ returned no record for the requested Valve game ID",
                {"provider": "stratz", "valve_game_id": match_id},
            )
        if (
            not isinstance(match, dict)
            or type(match.get("id")) is not int
            or match["id"] != match_id
        ):
            raise _schema_error("data.match.id")
        for name in (
            "startDateTime",
            "durationSeconds",
            "gameVersionId",
            "firstBloodTime",
            "radiantTeamId",
            "direTeamId",
        ):
            _typed(match, name, int, "data.match")
        if match.get("durationSeconds", 0) is not None and match.get("durationSeconds", 0) < 0:
            raise _schema_error("data.match.durationSeconds")
        stamp = match.get("startDateTime")
        if stamp is not None:
            try:
                if stamp <= 0:
                    raise ValueError
                datetime.fromtimestamp(stamp, UTC)
            except (ValueError, OverflowError, OSError):
                raise _schema_error("data.match.startDateTime") from None
        _typed(match, "didRadiantWin", bool, "data.match")
        for side in ("radiant", "dire"):
            values = match.get(f"{side}Kills")
            if values is not None and (
                not isinstance(values, list)
                or any(type(value) is not int or value < 0 for value in values)
            ):
                raise _schema_error(f"data.match.{side}Kills")
        for side in ("radiant", "dire"):
            team = match.get(f"{side}Team")
            if team is not None:
                if not isinstance(team, dict):
                    raise _schema_error(f"data.match.{side}Team")
                _typed(team, "id", int, f"data.match.{side}Team")
                _typed(team, "name", str, f"data.match.{side}Team")
                if team.get("id") != match.get(f"{side}TeamId"):
                    raise _schema_error(f"data.match.{side}Team.id")
        _validate_rows(
            match,
            "pickBans",
            "data.match",
            {
                "order": int,
                "isPick": bool,
                "heroId": int,
                "bannedHeroId": int,
                "isRadiant": bool,
            },
        )
        _validate_rows(
            match,
            "chatEvents",
            "data.match",
            {
                "time": int,
                "type": int,
                "fromHeroId": int,
                "toHeroId": int,
                "value": int,
                "isRadiant": bool,
            },
        )
        players = _validate_rows(
            match,
            "players",
            "data.match",
            {
                **{
                    k: int
                    for k in (
                        "steamAccountId",
                        "playerSlot",
                        "heroId",
                        "kills",
                        "deaths",
                        "assists",
                        "level",
                        "numLastHits",
                        "numDenies",
                        "heroDamage",
                        "towerDamage",
                        "heroHealing",
                        "networth",
                        "goldPerMinute",
                        "experiencePerMinute",
                        "neutral0Id",
                    )
                },
                **{f"item{i}Id": int for i in range(6)},
                **{f"backpack{i}Id": int for i in range(3)},
                "isRadiant": bool,
            },
        )
        for i, player in enumerate(players or []):
            for container in ("stats", "playbackData"):
                body = player.get(container)
                path = f"data.match.players[{i}].{container}"
                if body is None:
                    continue
                if not isinstance(body, dict):
                    raise _schema_error(path)
                event_types = {
                    "itemPurchases": {"time": int, "itemId": int},
                    "matchPlayerBuffEvent": {
                        "time": int,
                        "itemId": int,
                        "abilityId": int,
                        "stackCount": int,
                    },
                    "playerUpdateLevelEvents": {"time": int, "level": int},
                    "goldEvents": {
                        "time": int,
                        "amount": int,
                        "reason": str,
                        "isValidForStats": bool,
                    },
                    "deathEvents": {
                        k: int
                        for k in ("time", "attacker", "target", "goldFed", "goldLost", "timeDead")
                    },
                    "buyBackEvents": {"time": int},
                    "abilityLearnEvents": {
                        "time": int,
                        "abilityId": int,
                        "level": int,
                        "levelObtained": int,
                        "isTalent": bool,
                        "isUltimate": bool,
                    },
                    "inventoryEvents": {"time": int},
                }
                for key, fields in event_types.items():
                    rows = _validate_rows(body, key, path, fields)
                    if key == "inventoryEvents":
                        for j, row in enumerate(rows or []):
                            for slot in (
                                *[f"item{k}" for k in range(6)],
                                *[f"backPack{k}" for k in range(3)],
                                "neutral0",
                            ):
                                item = row.get(slot)
                                slot_path = f"{path}.{key}[{j}].{slot}"
                                if item is not None:
                                    if not isinstance(item, dict):
                                        raise _schema_error(slot_path)
                                    for field in ("itemId", "charges"):
                                        _typed(item, field, int, slot_path)
                report = body.get("heroDamageReport")
                if report is not None:
                    if not isinstance(report, dict):
                        raise _schema_error(f"{path}.heroDamageReport")
                    _validate_rows(
                        report,
                        "dealtTargets",
                        f"{path}.heroDamageReport",
                        {"target": int, "amount": int},
                    )
        try:
            return StratzGameRecord(
                match_id=match_id,
                retrieved_at=datetime.now(UTC),
                data=match,
                field_issues=_optional_field_issues(payload, match),
            )
        except ValidationError:
            raise _schema_error("data.match") from None


def _optional_field_issues(payload, match):
    issues = []
    players = match.get("players") or []
    for error in payload.get("errors") or []:
        path = error.get("path") if isinstance(error, dict) else None
        if not (
            isinstance(path, list)
            and len(path) >= 4
            and path[:2] == ["match", "players"]
            and type(path[2]) is int
            and 0 <= path[2] < len(players)
            and path[3] == "playbackData"
            and all(type(p) in (str, int) for p in path)
        ):
            raise StructuredToolError(
                "provider_error", "STRATZ game detail query failed", {"provider": "stratz"}
            )
        issues.append("players[" + str(path[2]) + "]." + ".".join(map(str, path[3:])))
    return list(dict.fromkeys(issues))


def _typed(record: dict, key: str, kind: type, path: str) -> None:
    if record.get(key) is not None and type(record[key]) is not kind:
        raise _schema_error(f"{path}.{key}")


def _validate_rows(record: dict, key: str, path: str, fields: dict[str, type]) -> list | None:
    rows = record.get(key)
    if rows is None:
        return None
    if not isinstance(rows, list):
        raise _schema_error(f"{path}.{key}")
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise _schema_error(f"{path}.{key}[{i}]")
        for name, kind in fields.items():
            _typed(row, name, kind, f"{path}.{key}[{i}]")
    return rows


def _schema_error(path: str) -> StructuredToolError:
    return StructuredToolError(
        "provider_schema_error",
        "STRATZ game detail response was invalid",
        {"provider": "stratz", "path": path},
    )
