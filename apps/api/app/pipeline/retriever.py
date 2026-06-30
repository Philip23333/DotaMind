import logging
import re
from difflib import SequenceMatcher
from typing import Any

from app.core.config import get_policy, get_settings
from app.data.mock_data import MOCK_HERO_STATS
from app.domain.evidence import EvidenceBundle
from app.domain.teams import (
    AmbiguousTeamError,
    TeamDataUnavailableError,
    TeamLookupError,
    TeamNotFoundError,
    TeamResolution,
    TeamSelectionNotFoundError,
)
from app.integrations.opendota.heroes import OpenDotaHeroes
from app.integrations.opendota.teams import OpenDotaTeams
from app.integrations.opendota.transport import OpenDotaTransport
from app.integrations.patch_notes import compute_hero_patch_score, get_item_changes, load_patch

logger = logging.getLogger(__name__)

_TIME_UNIT_DAYS = {
    "day": 1,
    "week": 7,
    "month": 30,
    "year": 365,
}


def _parse_days(time_range: str) -> int:
    """Convert a canonical duration such as last_2_months into days."""
    normalized = re.sub(r"[\s-]+", "_", time_range.casefold().strip())
    match = re.search(r"(\d+)_*(days?|weeks?|months?|years?)", normalized)
    if match:
        value = int(match.group(1))
        unit = match.group(2).rstrip("s")
        return value * _TIME_UNIT_DAYS[unit]

    for unit, days in _TIME_UNIT_DAYS.items():
        if normalized in {unit, f"last_{unit}"}:
            return days
    return get_policy().team_report.default_time_range_days


class RetrieverTool:
    """Deterministic evidence assembly. No LLM decisions live here."""

    def __init__(self) -> None:
        settings = get_settings()
        policy = get_policy()
        opendota_policy = policy.opendota
        match_detail_policy = policy.team_report.match_details
        self._policy = policy
        self._live_data_enabled = settings.live_data_enabled
        self._opendota_transport = OpenDotaTransport(
            settings.opendota_base_url,
            settings.opendota_api_key,
            request_timeout_seconds=opendota_policy.request_timeout_seconds,
            default_cache_ttl_seconds=opendota_policy.default_cache_ttl_seconds,
        )
        self._opendota_heroes = OpenDotaHeroes(self._opendota_transport)
        self._opendota_teams = OpenDotaTeams(
            self._opendota_transport,
            self._opendota_heroes,
            detail_sample_size=match_detail_policy.default_sample_size,
            max_detail_sample_size=match_detail_policy.max_sample_size,
            detail_concurrency=match_detail_policy.concurrency,
            match_detail_cache_ttl_seconds=match_detail_policy.cache_ttl_seconds,
        )

    async def aclose(self) -> None:
        await self._opendota_transport.aclose()

    async def retrieve_meta(self, role: str, patch: str = "latest") -> EvidenceBundle:
        if self._live_data_enabled:
            try:
                records = await self._opendota_heroes.get_stats_for_role(
                    role,
                    min_pub_pick=self._policy.hero_report.min_pub_pick,
                )
                if records:
                    records = self._inject_patch_scores(records, patch)
                    return EvidenceBundle(
                        task_type="meta_report",
                        query={"role": role, "patch": patch},
                        records=records,
                        sources=["opendota", "patch_json"],
                        data_source="mixed",
                    )
            except Exception as exc:
                logger.warning(
                    "OpenDota meta retrieval failed type=%s error=%r",
                    type(exc).__name__,
                    exc,
                )

        return EvidenceBundle(
            task_type="meta_report",
            query={"role": role, "patch": patch},
            records=self._mock_heroes(role),
            sources=["mock"],
            data_source="mock",
            missing=["live OpenDota hero stats"],
        )

    async def retrieve_patch(self, patch: str = "latest") -> EvidenceBundle:
        data = load_patch(patch)
        if data is None:
            return EvidenceBundle(
                task_type="patch_impact",
                query={"patch": patch},
                sources=["mock"],
                data_source="mock",
                missing=["structured patch JSON"],
            )
        return EvidenceBundle(
            task_type="patch_impact",
            query={"patch": data.get("patch", patch)},
            records=list(data.get("changes", [])),
            sources=["patch_json"],
            data_source="patch_json",
        )

    async def retrieve_team(
        self,
        team_name: str,
        time_range: str,
        team_id: int | None = None,
    ) -> EvidenceBundle:
        if not self._live_data_enabled:
            raise TeamDataUnavailableError(
                team_name,
                "Live OpenDota team data is disabled.",
            )

        days = _parse_days(time_range)
        try:
            cache_before = self._opendota_transport.cache_stats()
            teams = await self._opendota_teams.get_all()
            if team_id is None:
                resolution = self.resolve_team(team_name, teams)
                if resolution.status == "not_found":
                    raise TeamNotFoundError(team_name)
                if resolution.status == "ambiguous":
                    raise AmbiguousTeamError(
                        team_name,
                        resolution.candidates,
                        time_range,
                    )
            else:
                selected_team = next(
                    (team for team in teams if team.get("team_id") == team_id),
                    None,
                )
                if selected_team is None:
                    raise TeamSelectionNotFoundError(team_name)
                resolution = TeamResolution(
                    "resolved",
                    team_name,
                    team=selected_team,
                )

            data = await self._opendota_teams.get_report_data(
                team_name,
                days=days,
                resolved_team=resolution.team,
                cache_before=cache_before,
            )
            if not data:
                raise TeamNotFoundError(team_name)

            return EvidenceBundle(
                task_type="team_report",
                query={
                    "team_name": team_name,
                    "resolved_team_name": data.get("team_name"),
                    "team_id": data.get("team_id"),
                    "time_range": time_range,
                },
                records=[data],
                sources=["opendota"],
                data_source="opendota",
            )
        except TeamLookupError:
            raise
        except Exception as exc:
            logger.warning(
                "OpenDota team retrieval failed type=%s error=%r",
                type(exc).__name__,
                exc,
            )
            raise TeamDataUnavailableError(
                team_name,
                "OpenDota team data could not be retrieved.",
            ) from exc

    @classmethod
    def resolve_team(
        cls, requested_name: str, teams: list[dict[str, Any]]
    ) -> TeamResolution:
        """Resolve a user-provided team expression against the OpenDota directory."""
        query_variants = cls._team_query_variants(requested_name)
        if not query_variants:
            return TeamResolution("not_found", requested_name)

        exact_matches: list[dict[str, Any]] = []
        for team in teams:
            score, reason = cls._exact_team_score(query_variants, team)
            if score > 0:
                exact_matches.append(cls._team_candidate(team, score, reason))

        if exact_matches:
            return cls._select_team_resolution(requested_name, exact_matches, teams)

        fuzzy_matches = []
        primary_query = query_variants[0][0]
        cutoff = get_policy().team_report.resolution.fuzzy_score_cutoff
        for team in teams:
            score, reason = cls._fuzzy_team_score(primary_query, team)
            if score >= cutoff:
                fuzzy_matches.append(cls._team_candidate(team, score, reason))

        if not fuzzy_matches:
            return TeamResolution("not_found", requested_name)
        return cls._select_team_resolution(requested_name, fuzzy_matches, teams)

    @classmethod
    def _select_team_resolution(
        cls,
        requested_name: str,
        matches: list[dict[str, Any]],
        teams: list[dict[str, Any]],
    ) -> TeamResolution:
        matches.sort(
            key=lambda item: (
                float(item["match_score"]),
                int(item.get("last_match_time") or 0),
                float(item.get("rating") or 0),
            ),
            reverse=True,
        )
        best_score = float(matches[0]["match_score"])
        resolution_policy = get_policy().team_report.resolution
        plausible = [
            item
            for item in matches
            if best_score - float(item["match_score"])
            <= resolution_policy.ambiguity_score_delta
        ]
        if len(plausible) > 1:
            return TeamResolution(
                "ambiguous",
                requested_name,
                candidates=plausible[: resolution_policy.candidate_limit],
            )

        team_id = plausible[0]["team_id"]
        selected = next(team for team in teams if team.get("team_id") == team_id)
        return TeamResolution(
            "resolved",
            requested_name,
            team=selected,
            candidates=plausible,
        )

    @classmethod
    def _exact_team_score(
        cls,
        query_variants: list[tuple[str, float, str]],
        team: dict[str, Any],
    ) -> tuple[float, str]:
        name_variants = cls._team_value_variants(str(team.get("name") or ""))
        tag_variants = cls._team_value_variants(str(team.get("tag") or ""))
        best = (0.0, "")
        for query, weight, query_reason in query_variants:
            if query in name_variants:
                name_weight = weight + 5.0 if query_reason == "exact" else weight
                if name_weight > best[0]:
                    best = (name_weight, f"{query_reason} matched team name")
            if query in tag_variants and weight > best[0]:
                best = (weight, f"{query_reason} matched team tag")
        return best

    @classmethod
    def _fuzzy_team_score(
        cls, query: str, team: dict[str, Any]
    ) -> tuple[float, str]:
        name_variants = cls._team_value_variants(str(team.get("name") or ""))
        tag_variants = cls._team_value_variants(str(team.get("tag") or ""))
        name_score = max(
            (SequenceMatcher(None, query, value).ratio() * 70 + 5 for value in name_variants),
            default=0.0,
        )
        tag_score = max(
            (SequenceMatcher(None, query, value).ratio() * 70 for value in tag_variants),
            default=0.0,
        )
        if name_score >= tag_score:
            return round(name_score, 2), "fuzzy team name match"
        return round(tag_score, 2), "fuzzy team tag match"

    @classmethod
    def _team_query_variants(cls, value: str) -> list[tuple[str, float, str]]:
        expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value.strip())
        normalized = cls._normalize_team_value(expanded)
        if not normalized:
            return []

        tokens = normalized.split()
        generic_words = set(get_policy().team_report.resolution.generic_words)
        stripped_tokens = [token for token in tokens if token not in generic_words]
        stripped = " ".join(stripped_tokens) or normalized
        candidates = [
            (normalized, 100.0, "exact"),
            (stripped, 95.0, "normalized"),
            (stripped.replace(" ", ""), 90.0, "compact"),
        ]
        if len(stripped_tokens) > 1:
            candidates.append(
                ("".join(token[0] for token in stripped_tokens), 75.0, "acronym")
            )

        deduplicated: dict[str, tuple[float, str]] = {}
        for candidate, weight, reason in candidates:
            if candidate and weight > deduplicated.get(candidate, (0.0, ""))[0]:
                deduplicated[candidate] = (weight, reason)
        return [
            (candidate, weight, reason)
            for candidate, (weight, reason) in deduplicated.items()
        ]

    @classmethod
    def _team_value_variants(cls, value: str) -> set[str]:
        expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value.strip())
        normalized = cls._normalize_team_value(expanded)
        if not normalized:
            return set()
        tokens = normalized.split()
        generic_words = set(get_policy().team_report.resolution.generic_words)
        stripped = " ".join(token for token in tokens if token not in generic_words)
        return {variant for variant in (normalized, stripped, stripped.replace(" ", "")) if variant}

    @staticmethod
    def _normalize_team_value(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))

    @staticmethod
    def _team_candidate(
        team: dict[str, Any], score: float, reason: str
    ) -> dict[str, Any]:
        return {
            "team_id": team.get("team_id"),
            "name": team.get("name"),
            "tag": team.get("tag"),
            "rating": team.get("rating"),
            "last_match_time": team.get("last_match_time"),
            "match_score": round(score, 2),
            "match_reason": reason,
        }

    async def retrieve_claim(self, claim: str, game: str = "dota2") -> EvidenceBundle:
        normalized = claim.lower()
        records = [
            {
                "signal": "claim_entity_match",
                "value": "beastmaster" in normalized,
                "source": "rules",
            },
            {
                "signal": "role_match",
                "value": "offlane" in normalized or "position 3" in normalized,
                "source": "rules",
            },
        ]
        return EvidenceBundle(
            task_type="claim_verification",
            query={"claim": claim, "game": game},
            records=records,
            sources=["rules"],
            data_source="placeholder",
            missing=["live STRATZ pro draft sample", "fresh patch evidence"],
        )

    def _inject_patch_scores(
        self, records: list[dict[str, Any]], patch: str
    ) -> list[dict[str, Any]]:
        patch_policy = self._policy.patch_report
        scores = compute_hero_patch_score(
            patch,
            neutral_score=patch_policy.neutral_score,
            change_delta=patch_policy.change_delta,
        )
        if not scores:
            return records
        lookup = {self._key(name): score for name, score in scores.items()}
        for record in records:
            hero_name = str(record.get("hero") or record.get("localized_name") or "")
            record["patch_impact_score"] = lookup.get(
                self._key(hero_name),
                patch_policy.neutral_score,
            )
        return records

    @staticmethod
    def _mock_heroes(role: str) -> list[dict[str, Any]]:
        return [dict(hero) for hero in MOCK_HERO_STATS if hero["role"] == role]

    @staticmethod
    def _key(name: str) -> str:
        return name.lower().replace("-", "_").replace(" ", "_").replace("'", "")


def summarize_patch_records(
    records: list[dict[str, Any]],
    patch: str,
    *,
    neutral_score: float,
    change_delta: float,
    result_limit: int,
) -> dict[str, Any]:
    scores: dict[str, float] = {}
    for change in records:
        if change.get("target_type") != "hero":
            continue
        target = str(change.get("target", ""))
        scores.setdefault(target, neutral_score)
        if change.get("polarity") == "buff":
            scores[target] = min(1.0, scores[target] + change_delta)
        elif change.get("polarity") == "nerf":
            scores[target] = max(0.0, scores[target] - change_delta)

    winners = [
        _title(name)
        for name, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        if score > neutral_score
    ][:result_limit]
    losers = [
        _title(name)
        for name, score in sorted(scores.items(), key=lambda item: item[1])
        if score < neutral_score
    ][:result_limit]
    item_changes = get_item_changes(patch)
    item_buffs = [
        _title(str(c.get("target", ""))) for c in item_changes if c.get("polarity") == "buff"
    ]
    item_nerfs = [
        _title(str(c.get("target", ""))) for c in item_changes if c.get("polarity") == "nerf"
    ]
    total = len(records)
    buffs = sum(1 for c in records if c.get("polarity") == "buff")
    nerfs = sum(1 for c in records if c.get("polarity") == "nerf")
    summary = f"Patch {patch} contains {total} tracked changes ({buffs} buffs, {nerfs} nerfs)."
    return {
        "patch": patch,
        "summary": summary,
        "winners": winners or ["No clear hero winners detected"],
        "losers": losers or ["No clear hero losers detected"],
        "item_impacts": _impact_lines("Buffed items", item_buffs)
        + _impact_lines("Nerfed items", item_nerfs),
        "lineup_trends": [
            f"{len(winners)} heroes received net-positive changes.",
            "Draft priority should be reviewed against changed hero and item timings.",
        ],
        "practice_advice": [
            f"Review top changed heroes: {', '.join((winners + losers)[:4])}.",
            "Re-test item timings affected by the patch before ranked or scrim use.",
        ],
    }


def _impact_lines(label: str, values: list[str]) -> list[str]:
    unique = list(dict.fromkeys([value for value in values if value]))[:5]
    return [f"{label}: {', '.join(unique)}"] if unique else []


def _title(value: str) -> str:
    return value.replace("_", " ").title()
