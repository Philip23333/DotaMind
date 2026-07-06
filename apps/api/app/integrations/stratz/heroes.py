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
      stompWinCount
      stompLossCount
      csCount
    }
  }
}
"""

_HERO_POSITION_STATS_QUERY = """
query HeroPositionStats(
  $heroIds: [Short!],
  $bracketBasicIds: [RankBracketBasicEnum!],
  $positionIds: [MatchPlayerPositionType!],
  $week: Long
) {
  heroStats {
    stats(
      groupByPosition: true,
      heroIds: $heroIds,
      bracketBasicIds: $bracketBasicIds,
      positionIds: $positionIds,
      week: $week
    ) {
      heroId
      position
      matchCount
      winCount
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
        hero_id: int | None,
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

    async def hero_position_stats(
        self,
        *,
        hero_ids: list[int] | None = None,
        position_ids: list[str] | None = None,
        bracket_basic_ids: list[str] | None = None,
        week: int | None = None,
    ) -> list[dict[str, Any]]:
        payload = await self.transport.graphql(
            "HeroPositionStats",
            _HERO_POSITION_STATS_QUERY,
            {
                "heroIds": hero_ids,
                "bracketBasicIds": bracket_basic_ids,
                "positionIds": position_ids,
                "week": week,
            },
        )
        records = payload["data"]["heroStats"]["stats"]
        normalized: list[dict[str, Any]] = []
        for record in records:
            match_count = int(record.get("matchCount") or 0)
            win_count = int(record.get("winCount") or 0)
            normalized.append(
                {
                    "hero_id": record.get("heroId"),
                    "position": record.get("position"),
                    "match_count": match_count,
                    "win_count": win_count,
                    "match_win_rate": self._rate(win_count, match_count),
                }
            )
        return normalized

    @classmethod
    def _normalize_matchup_side(cls, side: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Integration layer is a thin relay: normalize field names only. Do NOT
        # sort here — ranking (by synergy) and top-K happen in the agentic layer
        # (`_filter_matchup_rows`), so the integration output preserves STRATZ's
        # raw iteration order. See docs/design/STRATZ工具审计与重构输入.md §4 P0-2.
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
                        "matchup_win_rate": cls._rate(win_count, match_count),
                        "synergy": record.get("synergy"),
                    }
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
            "stomp_win_count": int(record.get("stompWinCount") or 0),
            "stomp_loss_count": int(record.get("stompLossCount") or 0),
            "cs_count": int(record.get("csCount") or 0),
        }

    @staticmethod
    def _rate(value: int, total: int) -> float | None:
        if total <= 0:
            return None
        return round(value / total, 4)
