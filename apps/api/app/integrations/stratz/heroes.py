from typing import Any

from app.integrations.stratz.transport import StratzTransport

_HERO_VS_HERO_MATCHUP_QUERY = """
query HeroVsHeroMatchup(
  $heroId: Short!,
  $take: Int,
  $week: Long,
  $bracketBasicIds: [RankBracketBasicEnum!],
  $matchLimit: Int
) {
  heroStats {
    heroVsHeroMatchup(
      heroId: $heroId,
      take: $take,
      week: $week,
      bracketBasicIds: $bracketBasicIds,
      matchLimit: $matchLimit
    ) {
      advantage {
        heroId
        matchCountVs
        vs {
          heroId1
          heroId2
          matchCount
          winCount
          synergy
          winRateHeroId1
          winRateHeroId2
        }
      }
      disadvantage {
        heroId
        matchCountVs
        vs {
          heroId1
          heroId2
          matchCount
          winCount
          synergy
          winRateHeroId1
          winRateHeroId2
        }
      }
    }
  }
}
"""

_LANE_OUTCOME_QUERY = """
query HeroLaneOutcome(
  $heroId: Short,
  $isWith: Boolean!,
  $week: Long,
  $bracketBasicIds: [RankBracketBasicEnum!],
  $positionIds: [MatchPlayerPositionType!]
) {
  heroStats {
    laneOutcome(
      heroId: $heroId,
      isWith: $isWith,
      week: $week,
      bracketBasicIds: $bracketBasicIds,
      positionIds: $positionIds
    ) {
      heroId1
      heroId2
      position
      matchCount
      winCount
      lossCount
      drawCount
      matchWinCount
    }
  }
}
"""


class StratzHeroes:
    def __init__(self, transport: StratzTransport) -> None:
        self.transport = transport

    async def hero_vs_hero_matchup(
        self,
        hero_id: int,
        *,
        take: int = 10,
        week: int | None = None,
        bracket_basic_ids: list[str] | None = None,
        match_limit: int | None = None,
    ) -> dict[str, Any]:
        payload = await self.transport.graphql(
            "HeroVsHeroMatchup",
            _HERO_VS_HERO_MATCHUP_QUERY,
            {
                "heroId": hero_id,
                "take": take,
                "week": week,
                "bracketBasicIds": bracket_basic_ids,
                "matchLimit": match_limit,
            },
        )
        raw = payload["data"]["heroStats"]["heroVsHeroMatchup"]
        return {
            "hero_id": hero_id,
            "advantage": self._normalize_matchup_side(raw.get("advantage", [])),
            "disadvantage": self._normalize_matchup_side(raw.get("disadvantage", [])),
        }

    async def lane_outcome(
        self,
        hero_id: int,
        *,
        is_with: bool,
        week: int | None = None,
        bracket_basic_ids: list[str] | None = None,
        position_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        payload = await self.transport.graphql(
            "HeroLaneOutcome",
            _LANE_OUTCOME_QUERY,
            {
                "heroId": hero_id,
                "isWith": is_with,
                "week": week,
                "bracketBasicIds": bracket_basic_ids,
                "positionIds": position_ids,
            },
        )
        records = payload["data"]["heroStats"]["laneOutcome"]
        return [self._normalize_lane_outcome(record) for record in records]

    @classmethod
    def _normalize_matchup_side(cls, side: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for group in side:
            for record in group.get("vs") or []:
                match_count = int(record.get("matchCount") or 0)
                win_count = int(record.get("winCount") or 0)
                normalized.append(
                    {
                        "hero_id": record.get("heroId2"),
                        "target_hero_id": record.get("heroId1"),
                        "match_count": match_count,
                        "win_count": win_count,
                        "win_rate": cls._rate(win_count, match_count),
                        "synergy": record.get("synergy"),
                        "target_win_rate": record.get("winRateHeroId1"),
                        "hero_win_rate": record.get("winRateHeroId2"),
                    }
                )
        normalized.sort(
            key=lambda item: (
                float(item["synergy"] or 0),
                int(item["match_count"]),
            ),
            reverse=True,
        )
        return normalized

    @classmethod
    def _normalize_lane_outcome(cls, record: dict[str, Any]) -> dict[str, Any]:
        match_count = int(record.get("matchCount") or 0)
        match_win_count = int(record.get("matchWinCount") or 0)
        return {
            "hero_id": record.get("heroId2"),
            "target_hero_id": record.get("heroId1"),
            "position": record.get("position"),
            "match_count": match_count,
            "win_count": int(record.get("winCount") or 0),
            "loss_count": int(record.get("lossCount") or 0),
            "draw_count": int(record.get("drawCount") or 0),
            "match_win_count": match_win_count,
            "match_win_rate": cls._rate(match_win_count, match_count),
        }

    @staticmethod
    def _rate(value: int, total: int) -> float | None:
        if total <= 0:
            return None
        return round(value / total, 4)
