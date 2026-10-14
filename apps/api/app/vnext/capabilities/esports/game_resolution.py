"""Capability result and Service for cross-source single-game resolution."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictInt,
    StrictStr,
    TypeAdapter,
    field_validator,
    model_validator,
)

from app.vnext.providers.match_resolution.leagues import LeagueCandidateResult
from app.vnext.providers.match_resolution.request_flow import (
    GameResolutionReadAttempt,
    GameResolutionReadPolicy,
    PandaScoreOpenDotaGameResolutionProvider,
    ResolutionBudgetExceeded,
)
from app.vnext.providers.match_resolution.resolver import (
    MultiLeagueGameResolutionResult,
)
from app.vnext.tools.errors import StructuredToolError

ResolutionReason = Literal[
    "match_not_found",
    "target_game_not_found",
    "ambiguous_target_game",
    "target_not_ready",
    "insufficient_signals",
    "insufficient_context",
    "no_league_candidates",
    "no_candidates",
    "ambiguous",
    "evidence_insufficient",
    "mapping_conflict",
    "no_acceptable_candidate",
    "search_scope_incomplete",
]
ResolutionProviderId = Literal["pandascore", "opendota"]
_PositiveStrictInt = Annotated[StrictInt, Field(gt=0)]
_ATTEMPT_ADAPTER = TypeAdapter(GameResolutionReadAttempt)
_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, JsonValue])
_MATCH_ARTIFACT_PATH_PATTERN = r"^items\.[0-9]+$"
_RESOLUTION_CATEGORIES = frozenset(
    {
        "resolved",
        "ambiguous",
        "evidence_insufficient",
        "mapping_conflict",
        "no_acceptable_candidate",
        "no_candidates",
        "insufficient_signals",
        "target_game_not_found",
        "ambiguous_target_game",
        "target_not_ready",
        "search_scope_incomplete",
    }
)
_UNRESOLVED_REASONS = frozenset(
    {
        "match_not_found",
        "target_game_not_found",
        "ambiguous_target_game",
        "target_not_ready",
        "insufficient_signals",
        "insufficient_context",
        "no_league_candidates",
        "no_candidates",
        "ambiguous",
        "evidence_insufficient",
        "mapping_conflict",
        "no_acceptable_candidate",
        "search_scope_incomplete",
    }
)


class GameResolutionContractError(ValueError):
    """The internal Provider returned an incomplete or contradictory attempt."""


class EsportsGameResolveInput(BaseModel):
    """Continue from one Match-search Artifact and select a source game position."""

    model_config = ConfigDict(extra="forbid")

    match_artifact_ref: StrictStr = Field(
        min_length=1,
        description="Artifact reference returned by esports.match.search.",
    )
    match_path: StrictStr = Field(
        pattern=_MATCH_ARTIFACT_PATH_PATTERN,
        description="Path to one Match in the search result, formatted as items.N.",
    )
    game_position: _PositiveStrictInt = Field(
        description="Source Game position within the selected Match, not an array index."
    )


class EsportsGameResolutionResult(BaseModel):
    """Small capability envelope with the complete read attempt in ``data``."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    status: Literal["resolved", "unresolved"]
    game_position: _PositiveStrictInt
    valve_game_id: _PositiveStrictInt | None
    method: Literal["inferred_cross_source"] | None
    reason: ResolutionReason | None
    providers: list[ResolutionProviderId] = Field(min_length=1)
    retrieved_at: datetime
    data: dict[str, JsonValue]

    @field_validator("retrieved_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return value

    @field_validator("providers")
    @classmethod
    def require_unique_providers(
        cls, value: list[ResolutionProviderId]
    ) -> list[ResolutionProviderId]:
        if len(value) != len(set(value)):
            raise ValueError("providers must not contain duplicates")
        return value

    @model_validator(mode="after")
    def validate_status_fields(self) -> EsportsGameResolutionResult:
        if self.status == "resolved":
            if self.valve_game_id is None or self.method is None or self.reason is not None:
                raise ValueError("resolved results require an ID and method, without a reason")
        elif (
            self.valve_game_id is not None
            or self.method is not None
            or self.reason is None
        ):
            raise ValueError("unresolved results require a reason and no confirmed identity")
        return self


class GameResolutionService:
    """Convert one bounded Provider read attempt into a capability result."""

    def __init__(
        self,
        provider: PandaScoreOpenDotaGameResolutionProvider,
        *,
        policy: GameResolutionReadPolicy,
    ) -> None:
        self._provider = provider
        self._policy = policy

    async def resolve(
        self,
        match_id: int,
        game_position: int,
        *,
        confirmed_mappings: Mapping[int, int],
    ) -> EsportsGameResolutionResult:
        """Read once, then translate only the returned attempt and its outcome."""

        try:
            attempt = await self._provider.resolve(
                match_id,
                game_position,
                policy=self._policy,
                confirmed_mappings=confirmed_mappings,
            )
        except ResolutionBudgetExceeded as error:
            raise StructuredToolError(
                "tool_execution_error",
                "Game resolution read budget was exhausted",
                {
                    "category": "budget_exhausted",
                    "operation": error.operation,
                    "limit_name": error.limit_name,
                    "limit": error.limit,
                    "required": error.required,
                    "remaining": error.remaining,
                    "requests_started": error.requests_started,
                },
            ) from None

        _validate_attempt_identity(attempt, match_id, game_position)
        status, valve_game_id, method, reason = _map_attempt(attempt)
        data = _serialize_attempt(attempt)
        providers = ["pandascore"]
        if attempt.opendota_leagues is not None:
            providers.append("opendota")

        try:
            return EsportsGameResolutionResult(
                status=status,
                game_position=game_position,
                valve_game_id=valve_game_id,
                method=method,
                reason=reason,
                providers=providers,
                retrieved_at=attempt.retrieved_at,
                data=data,
            )
        except (TypeError, ValueError) as error:
            raise GameResolutionContractError(
                "internal read attempt does not satisfy the capability result contract"
            ) from error


def _validate_attempt_identity(
    attempt: GameResolutionReadAttempt,
    requested_match_id: int,
    requested_game_position: int,
) -> None:
    if not isinstance(attempt, GameResolutionReadAttempt):
        raise GameResolutionContractError("Provider returned an invalid read attempt")
    if (
        type(requested_match_id) is not int
        or type(requested_game_position) is not int
        or type(attempt.match_id) is not int
        or attempt.match_id != requested_match_id
        or type(attempt.game_position) is not int
        or attempt.game_position != requested_game_position
    ):
        raise GameResolutionContractError("Provider read attempt identity does not match request")
    if type(attempt.requests_started) is not int or attempt.requests_started <= 0:
        raise GameResolutionContractError("Provider read attempt has an invalid request count")
    if (
        not isinstance(attempt.retrieved_at, datetime)
        or attempt.retrieved_at.tzinfo is None
        or attempt.retrieved_at.utcoffset() is None
    ):
        raise GameResolutionContractError("Provider read attempt has an invalid retrieval time")


def _map_attempt(
    attempt: GameResolutionReadAttempt,
) -> tuple[
    Literal["resolved", "unresolved"],
    int | None,
    Literal["inferred_cross_source"] | None,
    ResolutionReason | None,
]:
    stage = attempt.stage
    if stage == "match_context":
        if (
            attempt.pandascore_match_context is not None
            or attempt.reason != "match_not_found"
            or attempt.target_game_result is not None
            or attempt.league_candidate_result is not None
            or attempt.resolution_result is not None
            or attempt.opendota_leagues is not None
            or attempt.league_matches_by_id
            or attempt.candidate_details
        ):
            raise GameResolutionContractError("incomplete match-context result")
        return "unresolved", None, None, "match_not_found"

    if attempt.pandascore_match_context is None:
        raise GameResolutionContractError("read attempt is missing its PandaScore Match")
    target = attempt.target_game_result
    if (
        target is None
        or type(target.game_position) is not int
        or target.game_position != attempt.game_position
    ):
        raise GameResolutionContractError("read attempt is missing its selected Game check")

    if stage == "target_game":
        if (
            target.category == "ready"
            or target.reason is None
            or attempt.reason != target.reason
            or attempt.league_candidate_result is not None
            or attempt.resolution_result is not None
            or attempt.opendota_leagues is not None
            or attempt.league_matches_by_id
            or attempt.candidate_details
        ):
            raise GameResolutionContractError("incomplete target-Game result")
        return "unresolved", None, None, _reason(target.category)

    if target.category != "ready" or target.target_game is None:
        raise GameResolutionContractError("later read stage has no ready target Game")
    league_result = attempt.league_candidate_result
    if league_result is None:
        raise GameResolutionContractError("read attempt is missing its League search result")
    if attempt.opendota_leagues is None:
        raise GameResolutionContractError("read attempt is missing its OpenDota League read")

    if stage == "league_candidates":
        if (
            attempt.resolution_result is not None
            or attempt.reason != league_result.reason
            or attempt.league_matches_by_id
            or attempt.candidate_details
        ):
            raise GameResolutionContractError("incomplete League candidate result")
        if league_result.category == "insufficient_context":
            _require_empty_league_candidates(league_result)
            return "unresolved", None, None, "insufficient_context"
        if league_result.category == "no_candidates":
            _require_empty_league_candidates(league_result)
            return "unresolved", None, None, "no_league_candidates"
        raise GameResolutionContractError("unexpected League candidate stop category")

    if stage != "resolution":
        raise GameResolutionContractError("Provider returned an unknown read stage")
    if league_result.category != "candidates_found":
        raise GameResolutionContractError("resolution stage has no complete candidate scope")
    if (
        not league_result.candidates
        or league_result.total_candidate_count != len(league_result.candidates)
        or league_result.reason is not None
    ):
        raise GameResolutionContractError(
            "resolution stage has an incomplete League candidate set"
        )
    result = attempt.resolution_result
    if not isinstance(result, MultiLeagueGameResolutionResult):
        raise GameResolutionContractError("read attempt is missing its resolution result")
    if (
        type(result.game_position) is not int
        or result.game_position != attempt.game_position
        or attempt.reason != result.reason
    ):
        raise GameResolutionContractError("resolution result contradicts its read attempt")
    if result.pandascore_match_id is not None and (
        type(result.pandascore_match_id) is not int
        or result.pandascore_match_id <= 0
        or result.pandascore_match_id != attempt.match_id
    ):
        raise GameResolutionContractError("resolution result has a mismatched Match identity")
    if result.pandascore_game_id is not None and (
        type(result.pandascore_game_id) is not int or result.pandascore_game_id <= 0
    ):
        raise GameResolutionContractError("resolution result has an invalid PandaScore Game ID")
    if not isinstance(result.category, str) or result.category not in _RESOLUTION_CATEGORIES:
        raise GameResolutionContractError("resolver returned an unknown result category")

    if result.category == "resolved":
        accepted_assessments = [
            item
            for item in result.candidate_assessments
            if item.status == "accepted"
        ]
        if (
            type(result.valve_game_id) is not int
            or result.valve_game_id <= 0
            or result.method != "inferred_cross_source"
            or result.reason is not None
            or result.missing_league_ids
            or result.pandascore_match_id != attempt.match_id
            or type(result.pandascore_game_id) is not int
            or result.pandascore_game_id <= 0
            or len(accepted_assessments) != 1
            or accepted_assessments[0].candidate_valve_game_id != result.valve_game_id
            or any(
                item.status not in {"accepted", "excluded"}
                for item in result.candidate_assessments
            )
        ):
            raise GameResolutionContractError("resolver returned an incomplete resolved identity")
        return "resolved", result.valve_game_id, result.method, None

    if result.valve_game_id is not None or result.method is not None or result.reason is None:
        raise GameResolutionContractError("resolver returned a contradictory unresolved result")
    return "unresolved", None, None, _reason(result.category)


def _reason(value: str) -> ResolutionReason:
    if not isinstance(value, str) or value not in _UNRESOLVED_REASONS:
        raise GameResolutionContractError("Provider returned an unknown unresolved category")
    return value  # type: ignore[return-value]


def _require_empty_league_candidates(result: LeagueCandidateResult) -> None:
    if (
        not result.reason
        or result.candidates
        or result.total_candidate_count != 0
    ):
        raise GameResolutionContractError("League search returned an incomplete empty result")


def _serialize_attempt(attempt: GameResolutionReadAttempt) -> dict[str, JsonValue]:
    try:
        document = _ATTEMPT_ADAPTER.dump_python(attempt, mode="json")
    except Exception as error:
        raise GameResolutionContractError(
            "Provider read attempt is not JSON serializable"
        ) from error
    if not isinstance(document, dict):
        raise GameResolutionContractError("serialized Provider read attempt is not an object")
    try:
        # Validate the entire nested document without pruning or normalizing facts.
        return _JSON_OBJECT_ADAPTER.validate_python(document)
    except (TypeError, ValueError) as error:
        raise GameResolutionContractError(
            "serialized Provider read attempt is not valid JSON"
        ) from error


__all__ = [
    "EsportsGameResolveInput",
    "EsportsGameResolutionResult",
    "GameResolutionContractError",
    "GameResolutionService",
    "ResolutionReason",
]
