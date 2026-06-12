from app.api.v1.schemas import PlannedTask


class PlannerAgent:
    """Routes a natural-language query to the MVP service most likely to answer it."""

    def plan(self, query: str) -> tuple[str, list[PlannedTask]]:
        normalized = query.lower()

        if "team" in normalized or "spirit" in normalized or "falcons" in normalized:
            service = "team_report"
            tasks = [
                PlannedTask(agent="planner", action="detect team-analysis intent"),
                PlannedTask(agent="data", action="collect recent pro match and draft signals"),
                PlannedTask(agent="reasoning", action="score patch adaptation"),
                PlannedTask(agent="verification", action="attach evidence and confidence"),
            ]
            return service, tasks

        if "patch" in normalized or "7." in normalized or "impact" in normalized:
            service = "patch_impact"
            tasks = [
                PlannedTask(agent="planner", action="detect patch-impact intent"),
                PlannedTask(agent="patch", action="extract hero, item, and mechanic changes"),
                PlannedTask(agent="data", action="compare post-patch trend signals"),
                PlannedTask(
                    agent="report",
                    action="summarize winners, losers, and practice advice",
                ),
            ]
            return service, tasks

        if "verify" in normalized or "claim" in normalized or "supported" in normalized:
            service = "claim_verification"
            tasks = [
                PlannedTask(agent="planner", action="detect verification intent"),
                PlannedTask(agent="data", action="collect matching evidence signals"),
                PlannedTask(agent="verification", action="assign verdict and missing data"),
            ]
            return service, tasks

        service = "meta_report"
        tasks = [
            PlannedTask(agent="planner", action="detect hero-meta intent"),
            PlannedTask(agent="data", action="collect role hero metrics"),
            PlannedTask(agent="reasoning", action="calculate meta score"),
            PlannedTask(agent="verification", action="attach evidence and confidence"),
            PlannedTask(agent="report", action="format ranked recommendations"),
        ]
        return service, tasks
