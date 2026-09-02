from __future__ import annotations

import json

import pytest

from app.vnext.providers.pandascore.capabilities import (
    CapabilitySchemaError,
    PandaScoreCapabilities,
    PandaScoreQueryValidationError,
)


def _error(exc_info: pytest.ExceptionInfo[PandaScoreQueryValidationError]) -> dict[str, object]:
    return exc_info.value.to_dict()


def test_loader_reads_generated_capabilities_and_resolves_normal_endpoints() -> None:
    capabilities = PandaScoreCapabilities.load()

    assert capabilities.endpoint("tournament", "all").path == "/dota2/tournaments"
    assert capabilities.endpoint("match", "running").path == "/dota2/matches/running"


def test_loader_rejects_invalid_generated_metadata(tmp_path) -> None:
    path = tmp_path / "capabilities.json"
    path.write_text(
        json.dumps({"schema_version": 2, "source": "pandascore", "game": "dota2", "resources": {}}),
        encoding="utf-8",
    )

    with pytest.raises(CapabilitySchemaError, match="schema_version"):
        PandaScoreCapabilities.load(path)


def test_endpoint_rejects_unsupported_resource_and_scope() -> None:
    capabilities = PandaScoreCapabilities.load()

    with pytest.raises(PandaScoreQueryValidationError) as resource_error:
        capabilities.endpoint("hero")
    assert _error(resource_error) == {
        "code": "unsupported_resource",
        "resource": "hero",
        "supported_resources": ["league", "match", "player", "serie", "team", "tournament"],
    }

    with pytest.raises(PandaScoreQueryValidationError) as scope_error:
        capabilities.endpoint("league", "running")
    assert _error(scope_error) == {
        "code": "unsupported_scope",
        "resource": "league",
        "scope": "running",
        "supported_scopes": ["all"],
    }


def test_validator_accepts_native_serie_tournament_and_match_queries() -> None:
    capabilities = PandaScoreCapabilities.load()

    capabilities.validate_query({"resource": "serie", "filter": {"league_id": 4106, "year": 2026}})
    capabilities.validate_query(
        {"resource": "tournament", "filter": {"serie_id": 10828, "name": "Group Stage"}}
    )
    capabilities.validate_query(
        {
            "resource": "match",
            "filter": {"league_id": 4106, "serie_id": 10828, "tournament_id": 21698},
        }
    )


def test_validator_reports_all_unsupported_tournament_filter_fields() -> None:
    capabilities = PandaScoreCapabilities.load()

    with pytest.raises(PandaScoreQueryValidationError) as error:
        capabilities.validate_query(
            {"resource": "tournament", "filter": {"league_id": 4106, "year": 2026}}
        )
    assert _error(error)["code"] == "unsupported_field"
    assert _error(error)["fields"] == ["league_id", "year"]


def test_validator_accepts_and_rejects_sort_fields() -> None:
    capabilities = PandaScoreCapabilities.load()

    capabilities.validate_query({"resource": "match", "sort": ["-begin_at", "name"]})
    with pytest.raises(PandaScoreQueryValidationError) as error:
        capabilities.validate_query({"resource": "match", "sort": ["-banana"]})
    assert _error(error)["code"] == "unsupported_field"
    assert _error(error)["field"] == "banana"


def test_validator_validates_enum_and_range_values() -> None:
    capabilities = PandaScoreCapabilities.load()

    capabilities.validate_query({"resource": "tournament", "filter": {"tier": "s"}})
    with pytest.raises(PandaScoreQueryValidationError) as enum_error:
        capabilities.validate_query({"resource": "tournament", "filter": {"tier": "super-premium"}})
    assert _error(enum_error)["code"] == "invalid_value"
    assert _error(enum_error)["allowed_values"] == ["a", "b", "c", "d", "s", "unranked"]

    capabilities.validate_query(
        {
            "resource": "match",
            "range": {"begin_at": ["2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"]},
        }
    )
    with pytest.raises(PandaScoreQueryValidationError) as range_error:
        capabilities.validate_query(
            {"resource": "match", "range": {"begin_at": ["2026-01-01T00:00:00Z"]}}
        )
    assert _error(range_error)["reason"] == "range_requires_two_values"


def test_validator_accepts_scalar_and_list_values_for_multiple_fields() -> None:
    capabilities = PandaScoreCapabilities.load()

    capabilities.validate_query({"resource": "serie", "filter": {"year": 2026}})
    capabilities.validate_query({"resource": "serie", "filter": {"year": [2025, 2026]}})


def test_validator_rejects_boolean_as_integer_and_multiple_search_values() -> None:
    capabilities = PandaScoreCapabilities.load()

    with pytest.raises(PandaScoreQueryValidationError) as integer_error:
        capabilities.validate_query({"resource": "serie", "filter": {"year": True}})
    assert _error(integer_error)["reason"] == "type_mismatch"

    with pytest.raises(PandaScoreQueryValidationError) as search_error:
        capabilities.validate_query(
            {"resource": "league", "search": {"name": ["The International"]}}
        )
    assert _error(search_error)["reason"] == "multiple_values_not_allowed"


def test_validator_rejects_special_team_route_as_normal_scope() -> None:
    capabilities = PandaScoreCapabilities.load()

    with pytest.raises(PandaScoreQueryValidationError) as error:
        capabilities.validate_query({"resource": "team", "scope": "by_serie"})
    assert _error(error) == {
        "code": "unsupported_scope",
        "resource": "team",
        "scope": "by_serie",
        "supported_scopes": ["all"],
    }


def test_validator_normalizes_and_validates_pagination() -> None:
    capabilities = PandaScoreCapabilities.load()

    normalized = capabilities.validate_query({"resource": "league", "page": 2, "page_size": 25})
    assert normalized.page == 2
    assert normalized.page_size == 25

    with pytest.raises(PandaScoreQueryValidationError) as page_error:
        capabilities.validate_query({"resource": "league", "page": 0})
    assert _error(page_error) == {
        "code": "invalid_value",
        "field": "page",
        "reason": "page_must_be_positive_integer",
    }

    with pytest.raises(PandaScoreQueryValidationError) as page_size_error:
        capabilities.validate_query({"resource": "league", "page_size": 101})
    assert _error(page_size_error) == {
        "code": "invalid_value",
        "field": "page_size",
        "reason": "page_size_out_of_range",
    }
