class ReportAgent:
    """Small narrative helpers for service responses."""

    def meta_summary(self, role: str, hero_count: int) -> str:
        return (
            f"Sample {role} report ranks {hero_count} heroes by win rate, pick rate, "
            "pro presence, patch impact, and trend signals."
        )

    def analysis_steps(self) -> list[str]:
        return [
            "Normalize role and patch request.",
            "Collect hero statistics from configured data sources.",
            "Calculate MVP meta score using weighted signals.",
            "Attach evidence labels and confidence.",
            "Return a structured report for web and agent callers.",
        ]
