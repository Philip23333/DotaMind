"""Agent-visible reference-schema contracts remain strict and readable."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from app.vnext.artifacts.models import ArtifactRef
from app.vnext.composition import build_vnext_registry
from app.vnext.llm.openai_compatible import OpenAICompatibleModelClient
from app.vnext.llm.protocol import ModelRequest, UserMessage
from app.vnext.tools.artifacts.retrieval import ArtifactReadInput
from app.vnext.tools.domain.competitions import CompetitionListMatchesInput
from app.vnext.tools.domain.matches import MatchGetDetailInput, MatchSearchInput
from app.vnext.tools.domain.players import PlayerGetDetailInput
from app.vnext.tools.domain.teams import TeamGetDetailInput
from tests.vnext.phase2_support import fixture_services, fixture_vnext_services

_COMPETITION_VALUE = "competition:0123456789abcdef01234567"
_MATCH_VALUE = "match:0123456789abcdef01234567"
_GAME_VALUE = "game:0123456789abcdef01234567"
_TEAM_VALUE = "team:0123456789abcdef01234567"
_PLAYER_VALUE = "player:0123456789abcdef01234567"


def _tool_schemas() -> dict[str, dict[str, Any]]:
    competition_service, match_service, panda, opendota = fixture_services()
    registry = build_vnext_registry(
        fixture_vnext_services(competition_service, match_service, panda, opendota)
    )
    return {tool.name: tool.input_schema for tool in registry.schemas()}


def _reference_definition(
    schema: dict[str, Any],
    field_name: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    field_schema = schema["properties"][field_name]
    reference = field_schema.get("$ref")
    if reference is None:
        reference = next(
            candidate["$ref"]
            for candidate in field_schema["anyOf"]
            if "$ref" in candidate
        )
    definition_name = reference.rsplit("/", maxsplit=1)[-1]
    return field_schema, schema["$defs"][definition_name]


def test_agent_visible_reference_schemas_explain_nested_object_inputs() -> None:
    schemas = _tool_schemas()

    competition_field, competition_ref = _reference_definition(
        schemas["competitions.list_matches"], "competition_ref"
    )
    assert "returned by competitions.search" in competition_field["description"]
    assert "whole object unchanged" in competition_field["description"]
    assert competition_ref["type"] == "object"
    assert "bare string" in competition_ref["description"]
    assert competition_ref["examples"] == [{"value": _COMPETITION_VALUE}]
    assert "inside this reference object" in competition_ref["properties"]["value"]["description"]

    search_field, search_competition_ref = _reference_definition(
        schemas["matches.search"], "competition"
    )
    assert "named competition, not competition_ref" in search_field["description"]
    assert search_competition_ref["type"] == "object"

    match_field, match_ref = _reference_definition(schemas["matches.get_detail"], "match_ref")
    game_field, game_ref = _reference_definition(schemas["matches.get_detail"], "game_ref")
    assert "exactly one of match_ref or game_ref" in match_field["description"]
    assert "exactly one of match_ref or game_ref" in game_field["description"]
    assert match_ref["type"] == game_ref["type"] == "object"
    assert match_ref["examples"] == [{"value": _MATCH_VALUE}]
    assert game_ref["examples"] == [{"value": _GAME_VALUE}]

    team_field, team_ref = _reference_definition(schemas["teams.get_detail"], "team_ref")
    player_field, player_ref = _reference_definition(
        schemas["players.get_detail"], "player_ref"
    )
    assert "Complete TeamRef object" in team_field["description"]
    assert "Complete PlayerRef object" in player_field["description"]
    assert team_ref["type"] == player_ref["type"] == "object"
    assert "bare string" in team_ref["description"]
    assert "bare string" in player_ref["description"]
    assert team_ref["examples"] == [{"value": _TEAM_VALUE}]
    assert player_ref["examples"] == [{"value": _PLAYER_VALUE}]

    artifact_field, artifact_ref = _reference_definition(schemas["artifact.read"], "ref")
    assert "returned by artifact.search" in artifact_field["description"]
    assert artifact_ref["type"] == "object"
    assert "bare string" in artifact_ref["description"]
    assert artifact_ref["examples"][0]["artifact_type"] == "game_summary"


@pytest.mark.parametrize(
    ("input_model", "field_name", "value", "valid_arguments"),
    [
        (
            CompetitionListMatchesInput,
            "competition_ref",
            _COMPETITION_VALUE,
            {"competition_ref": {"value": _COMPETITION_VALUE}},
        ),
        (
            MatchSearchInput,
            "competition",
            _COMPETITION_VALUE,
            {"competition": {"value": _COMPETITION_VALUE}},
        ),
        (
            MatchGetDetailInput,
            "match_ref",
            _MATCH_VALUE,
            {"match_ref": {"value": _MATCH_VALUE}},
        ),
        (
            TeamGetDetailInput,
            "team_ref",
            _TEAM_VALUE,
            {"team_ref": {"value": _TEAM_VALUE}},
        ),
        (
            PlayerGetDetailInput,
            "player_ref",
            _PLAYER_VALUE,
            {"player_ref": {"value": _PLAYER_VALUE}},
        ),
    ],
)
def test_domain_reference_inputs_reject_string_forms(
    input_model: type[BaseModel],
    field_name: str,
    value: str,
    valid_arguments: dict[str, object],
) -> None:
    assert input_model.model_validate(valid_arguments)
    for invalid_value in (value, json.dumps({"value": value})):
        with pytest.raises(ValidationError):
            input_model.model_validate({field_name: invalid_value})


def test_artifact_reference_input_remains_a_strict_nested_object() -> None:
    valid_ref = {
        "id": "game_summary:4:8123456789",
        "artifact_type": "game_summary",
        "schema_version": "4",
    }
    assert ArtifactReadInput.model_validate({"ref": valid_ref}).ref == ArtifactRef(**valid_ref)
    for invalid_value in (valid_ref["id"], json.dumps(valid_ref)):
        with pytest.raises(ValidationError):
            ArtifactReadInput.model_validate({"ref": invalid_value})


def test_openai_compatible_payload_preserves_reference_schema_metadata() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.read())
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]},
            request=request,
        )

    client = OpenAICompatibleModelClient(
        base_url="https://provider.test/v1",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )
    competition_schema = _tool_schemas()["matches.search"]
    asyncio.run(
        client.complete(
            ModelRequest(
                messages=[UserMessage(content="find matches")],
                tools=[
                    build_vnext_registry(
                        fixture_vnext_services(*fixture_services())
                    ).get("matches.search").schema()
                ],
            )
        )
    )

    provider_schema = seen["payload"]["tools"][0]["function"]["parameters"]
    assert provider_schema == competition_schema
    provider_field, provider_ref = _reference_definition(provider_schema, "competition")
    assert "named competition, not competition_ref" in provider_field["description"]
    assert provider_ref["examples"] == [{"value": _COMPETITION_VALUE}]
