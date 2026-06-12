class MetaReasoningAgent:
    """Converts normalized signals into MVP scoring outputs."""

    def meta_score(
        self,
        *,
        win_rate: float,
        pick_rate: float,
        pro_presence: float,
        patch_impact_score: float,
        trend_score: float,
    ) -> int:
        win_rate_score = self._normalize(win_rate, low=0.45, high=0.56)
        pick_rate_score = self._normalize(pick_rate, low=0.02, high=0.18)

        score = (
            0.30 * win_rate_score
            + 0.25 * pick_rate_score
            + 0.20 * pro_presence
            + 0.15 * patch_impact_score
            + 0.10 * trend_score
        )
        return round(score * 100)

    def confidence(self, values: list[float]) -> float:
        if not values:
            return 0.0
        return round(sum(values) / len(values), 2)

    @staticmethod
    def _normalize(value: float, *, low: float, high: float) -> float:
        if value <= low:
            return 0.0
        if value >= high:
            return 1.0
        return (value - low) / (high - low)
