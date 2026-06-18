import logging
import re
from typing import Any

from app.core.config import get_settings
from app.domain.tasks import PlannedTask, ReportRequest
from app.llm.provider import get_llm_provider

logger = logging.getLogger(__name__)

_ROLE_ALIASES = {
    "carry": "carry",
    "safe lane": "carry",
    "safelane": "carry",
    "position 1": "carry",
    "pos 1": "carry",
    "mid": "mid",
    "midlane": "mid",
    "position 2": "mid",
    "pos 2": "mid",
    "offlane": "offlane",
    "off lane": "offlane",
    "position 3": "offlane",
    "pos 3": "offlane",
    "support": "support",
    "position 4": "support",
    "position 5": "support",
    "pos 4": "support",
    "pos 5": "support",
}

_TOOL_NAME_TO_TASK = {
    "get_meta_report": "meta_report",
    "get_patch_impact": "patch_impact",
    "get_team_report": "team_report",
    "verify_meta_claim": "claim_verification",
}

_SYSTEM_PROMPT = (
    "You are the MetaMind Orchestrator. Your job is to read a Dota 2"
    " question and decide which report tool to call.\n\n"
    "Available tools:\n"
    "- get_meta_report: ranked hero recommendations for a role and patch\n"
    "- get_patch_impact: winners/losers and item impact for a patch\n"
    "- get_team_report: recent form and draft preferences for a pro team\n"
    "- verify_meta_claim: evidence-backed verdict for a meta claim\n\n"
    "Rules:\n"
    '1. If the user asks about hero strength, pick rates, or "best heroes",'
    " call get_meta_report.\n"
    '2. If the user asks "what changed", "patch", "buff", or "nerf", call'
    " get_patch_impact.\n"
    '3. If the user mentions a team name (e.g. Team Spirit), call'
    " get_team_report.\n"
    '4. If the user asks to verify or fact-check a claim, call'
    " verify_meta_claim.\n"
    "5. Extract role, patch version, and team name from the query when present."
    " Default role to 'offlane' if not specified."
)

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_meta_report",
            "description": "Return ranked hero recommendations for a game, patch, and role.",
            "parameters": {
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "enum": ["carry", "mid", "offlane", "support"],
                        "description": "Dota 2 position/role",
                    },
                    "patch": {
                        "type": "string",
                        "description": "Patch version like '7.41d' or 'latest'",
                    },
                },
                "required": ["role"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_patch_impact",
            "description": "Return winners, losers, item impacts, and lineup trends for a patch.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "string",
                        "description": "Patch version like '7.41d' or 'latest'",
                    },
                    "role": {
                        "type": "string",
                        "enum": ["carry", "mid", "offlane", "support"],
                        "description": "Optional role filter",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_team_report",
            "description": "Return recent professional team intelligence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "team_name": {
                        "type": "string",
                        "description": "Professional Dota 2 team name",
                    },
                    "time_range": {
                        "type": "string",
                        "description": "Time window, e.g. 'last_30_days'",
                    },
                },
                "required": ["team_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "verify_meta_claim",
            "description": "Check whether a game meta claim has evidence support.",
            "parameters": {
                "type": "object",
                "properties": {
                    "claim": {
                        "type": "string",
                        "description": "The meta claim to verify",
                    },
                },
                "required": ["claim"],
            },
        },
    },
]


class OrchestratorAgent:
    """Single planning boundary: LLM function calling with rule fallback."""

    def __init__(self) -> None:
        settings = get_settings()
        self.llm_enabled = settings.llm_enabled
        self.llm = None
        if self.llm_enabled:
            try:
                self.llm = get_llm_provider()
            except Exception as exc:
                logger.warning("LLM provider unavailable, orchestrator stays rule-based: %s", exc)
                self.llm_enabled = False

    async def plan_query(self, query: str, game: str = "dota2") -> ReportRequest:
        if self.llm_enabled and self.llm:
            try:
                request = await self._plan_with_llm(query, game)
                if request is not None:
                    return request
            except Exception as exc:
                logger.warning("LLM planning failed, falling back to rules: %s", exc)

        return self._plan_with_rules(query, game)

    async def _plan_with_llm(self, query: str, game: str) -> ReportRequest | None:
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": query},
        ]
        logger.info("Orchestrator LLM planning query_chars=%s", len(query))
        result = await self.llm.complete_with_tools(  # type: ignore[union-attr]
            messages,
            _TOOLS,
            temperature=0.0,
            max_tokens=300,
        )
        if result is None:
            logger.info("Orchestrator LLM returned no tool call, falling back to rules")
            return None

        tool_name = result["name"]
        args = result["arguments"]
        task_type = _TOOL_NAME_TO_TASK.get(tool_name)
        if task_type is None:
            logger.warning("Orchestrator LLM returned unknown tool: %s", tool_name)
            return None

        logger.info("Orchestrator LLM routed tool=%s task=%s args=%s", tool_name, task_type, args)
        return self._build_request(task_type, game, query, args)

    def _build_request(
        self, task_type: str, game: str, query: str, args: dict[str, Any]
    ) -> ReportRequest:
        role = self._normalize_role(args.get("role")) if args.get("role") else None
        patch = args.get("patch") or "latest"
        team_name = args.get("team_name")
        claim = args.get("claim") or query
        time_range = args.get("time_range") or "last_30_days"

        if task_type == "meta_report" and not role:
            role = "offlane"

        return ReportRequest(
            task_type=task_type,  # type: ignore[arg-type]
            game=game,
            query=query,
            patch=patch,
            role=role,
            team_name=team_name,
            time_range=time_range,
            claim=claim if task_type == "claim_verification" else None,
            trace=[
                PlannedTask(
                    agent="orchestrator",
                    action=f"LLM routed to {task_type} via function calling",
                )
            ],
        )

    def _plan_with_rules(self, query: str, game: str) -> ReportRequest:
        normalized = query.lower().strip()
        trace = [PlannedTask(agent="orchestrator", action="classify user intent (rule-based)")]

        if any(t in normalized for t in ("verify", "claim", "supported", "true?")):
            return ReportRequest(
                task_type="claim_verification",
                game=game,
                query=query,
                claim=query,
                trace=trace
                + [PlannedTask(agent="orchestrator", action="route to claim verification")],
            )

        if any(t in normalized for t in ("team", "spirit", "falcons", "liquid", "gg")):
            return ReportRequest(
                task_type="team_report",
                game=game,
                query=query,
                team_name=self._extract_team_name(query),
                trace=trace + [PlannedTask(agent="orchestrator", action="route to team report")],
            )

        if any(t in normalized for t in ("patch", "changed", "impact", "nerf", "buff")):
            return ReportRequest(
                task_type="patch_impact",
                game=game,
                query=query,
                patch=self._extract_patch(query),
                role=self._extract_role(query),
                trace=trace + [PlannedTask(agent="orchestrator", action="route to patch impact")],
            )

        return ReportRequest(
            task_type="meta_report",
            game=game,
            query=query,
            patch=self._extract_patch(query),
            role=self._extract_role(query) or "offlane",
            trace=trace + [PlannedTask(agent="orchestrator", action="route to meta report")],
        )

    def plan_structured(
        self,
        task_type: str,
        *,
        game: str = "dota2",
        patch: str = "latest",
        role: str | None = None,
        team_name: str | None = None,
        time_range: str = "last_30_days",
        claim: str | None = None,
    ) -> ReportRequest:
        return ReportRequest(
            task_type=task_type,  # type: ignore[arg-type]
            game=game,
            patch=patch,
            role=self._normalize_role(role) if role else None,
            team_name=team_name,
            time_range=time_range,
            claim=claim,
            trace=[
                PlannedTask(agent="orchestrator", action=f"accept structured {task_type} request")
            ],
        )

    def _extract_role(self, query: str) -> str | None:
        normalized = query.lower()
        for label, role in _ROLE_ALIASES.items():
            if label in normalized:
                return role
        return None

    def _normalize_role(self, role: str | None) -> str | None:
        if role is None:
            return None
        normalized = role.lower().strip()
        return _ROLE_ALIASES.get(normalized, normalized)

    @staticmethod
    def _extract_patch(query: str) -> str:
        match = re.search(r"\b\d+\.\d+[a-z]?\b", query.lower())
        return match.group(0) if match else "latest"

    @staticmethod
    def _extract_team_name(query: str) -> str:
        known = ["Team Spirit", "Team Falcons", "Team Liquid", "Gaimin Gladiators"]
        lowered = query.lower()
        for team in known:
            if team.lower() in lowered or team.replace("Team ", "").lower() in lowered:
                return team
        return "Team Spirit"
