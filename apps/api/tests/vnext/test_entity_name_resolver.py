from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from app.integrations.valve.catalog_repository import (
    CatalogLookupError,
    DotaCatalogRepository,
)
from app.vnext.catalog import EntityNameResolver

GENERATED_AT = datetime(2026, 9, 20, 12, 30, tzinfo=timezone.utc)


class FakeCatalogRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.records: dict[tuple[str, int], Any] = {
            ("hero", 1): SimpleNamespace(name_en="Hero One", name_zh="英雄一"),
            ("item", 1): SimpleNamespace(name_en="Item One", name_zh="物品一"),
            ("ability", 5094): SimpleNamespace(name_en="Ability", name_zh="技能"),
            ("ability", 7): SimpleNamespace(name_en="", name_zh=""),
        }
        self.errors: dict[tuple[str, int], Exception] = {}
        self.metadata_calls = 0

    def snapshot_metadata(self) -> dict[str, Any]:
        self.metadata_calls += 1
        return {
            "patch": "7.39e",
            "generated_at": GENERATED_AT.isoformat(),
            "schema_version": 3,
        }

    def _get(self, kind: str, identifier: int) -> Any:
        self.calls.append((kind, identifier))
        error = self.errors.get((kind, identifier))
        if error is not None:
            raise error
        try:
            return self.records[(kind, identifier)]
        except KeyError as exc:
            raise CatalogLookupError(f"{kind} not found: {identifier}") from exc

    def get_hero(self, identifier: int) -> Any:
        return self._get("hero", identifier)

    def get_item(self, identifier: int) -> Any:
        return self._get("item", identifier)

    def get_ability(self, identifier: int) -> Any:
        return self._get("ability", identifier)


@pytest.mark.parametrize(
    ("kind", "identifier", "expected_call"),
    [
        ("hero", 1, ("hero", 1)),
        ("item", 1, ("item", 1)),
        ("ability", 5094, ("ability", 5094)),
    ],
)
def test_resolver_dispatches_kind_and_preserves_catalog_names_and_version(
    kind: str, identifier: int, expected_call: tuple[str, int]
) -> None:
    repository = FakeCatalogRepository()

    result = EntityNameResolver(repository).resolve_many(kind=kind, ids=[identifier])  # type: ignore[arg-type]

    record = repository.records[expected_call]
    assert repository.calls == [expected_call]
    assert result.kind == kind
    assert result.entries[0].model_dump() == {
        "id": identifier,
        "status": "found",
        "name_en": record.name_en,
        "name_zh": record.name_zh,
    }
    assert result.catalog_version.model_dump() == {
        "source": "valve_dota2_datafeed",
        "patch": "7.39e",
        "generated_at": GENERATED_AT,
        "schema_version": 3,
    }


def test_resolver_deduplicates_in_first_seen_order_and_never_looks_up_zero() -> None:
    repository = FakeCatalogRepository()

    result = EntityNameResolver(repository).resolve_many(
        kind="ability", ids=[5094, 0, 5094, 999999]
    )

    assert [entry.id for entry in result.entries] == [5094, 0, 999999]
    assert [entry.status for entry in result.entries] == ["found", "unknown", "unknown"]
    assert repository.calls == [("ability", 5094), ("ability", 999999)]


def test_batch_size_is_not_limited_by_catalog_lookup_tool_bound() -> None:
    repository = FakeCatalogRepository()
    identifiers = list(range(1000, 1025))

    result = EntityNameResolver(repository).resolve_many(kind="item", ids=identifiers)

    assert [entry.id for entry in result.entries] == identifiers
    assert all(entry.status == "unknown" for entry in result.entries)
    assert repository.calls == [("item", identifier) for identifier in identifiers]


def test_only_catalog_lookup_errors_become_unknown() -> None:
    repository = FakeCatalogRepository()
    repository.errors[("item", 99)] = CatalogLookupError("missing")

    result = EntityNameResolver(repository).resolve_many(kind="item", ids=[99])

    assert result.entries[0].model_dump() == {
        "id": 99,
        "status": "unknown",
        "name_en": None,
        "name_zh": None,
    }

    repository.errors[("item", 100)] = OSError("catalog read failed")
    with pytest.raises(OSError, match="catalog read failed"):
        EntityNameResolver(repository).resolve_many(kind="item", ids=[100])


@pytest.mark.parametrize("invalid", [True, -1, 1.5, "1", None])
def test_invalid_id_values_are_rejected(invalid: object) -> None:
    repository = FakeCatalogRepository()

    with pytest.raises(ValueError):
        EntityNameResolver(repository).resolve_many(kind="hero", ids=[invalid])  # type: ignore[list-item]

    assert repository.calls == []
    assert repository.metadata_calls == 0


def test_all_ids_are_validated_before_any_repository_access() -> None:
    repository = FakeCatalogRepository()

    with pytest.raises(ValueError):
        EntityNameResolver(repository).resolve_many(
            kind="hero", ids=[1, 2, "invalid"]  # type: ignore[list-item]
        )

    assert repository.calls == []
    assert repository.metadata_calls == 0


@pytest.mark.parametrize("kind", ["player", "", None, True, 1, [], {}])
def test_invalid_kind_is_rejected_before_repository_access(kind: object) -> None:
    repository = FakeCatalogRepository()

    with pytest.raises(ValueError):
        EntityNameResolver(repository).resolve_many(
            kind=kind, ids=[1]  # type: ignore[arg-type]
        )

    assert repository.calls == []
    assert repository.metadata_calls == 0


@pytest.mark.parametrize("ids", ["1", b"1", bytearray(b"1")])
def test_non_sequence_id_containers_are_rejected(ids: object) -> None:
    with pytest.raises(ValueError):
        EntityNameResolver(FakeCatalogRepository()).resolve_many(
            kind="hero", ids=ids  # type: ignore[arg-type]
        )


def test_empty_batch_is_valid_and_returns_repository_version() -> None:
    repository = FakeCatalogRepository()

    result = EntityNameResolver(repository).resolve_many(kind="hero", ids=[])

    assert result.entries == []
    assert result.catalog_version.generated_at == GENERATED_AT
    assert repository.calls == []


def test_empty_names_stay_missing_without_translation_or_internal_name_fallback() -> None:
    repository = FakeCatalogRepository()
    repository.records[("ability", 7)] = SimpleNamespace(
        name_en="", name_zh="", internal_name="some_internal_ability"
    )

    entry = EntityNameResolver(repository).resolve_many(kind="ability", ids=[7]).entries[0]

    assert entry.status == "found"
    assert entry.name_en is None
    assert entry.name_zh is None


def test_same_numeric_id_is_resolved_independently_for_each_kind() -> None:
    repository = FakeCatalogRepository()
    resolver = EntityNameResolver(repository)

    hero = resolver.resolve_many(kind="hero", ids=[1]).entries[0]
    item = resolver.resolve_many(kind="item", ids=[1]).entries[0]

    assert hero.name_en == "Hero One"
    assert item.name_en == "Item One"
    assert repository.calls == [("hero", 1), ("item", 1)]


def test_inputs_and_results_are_isolated_between_calls() -> None:
    repository = FakeCatalogRepository()
    resolver = EntityNameResolver(repository)
    input_ids = [1, 1]

    first = resolver.resolve_many(kind="hero", ids=input_ids)
    assert input_ids == [1, 1]
    first.entries[0].name_en = "mutated output"
    first.entries.clear()
    second = resolver.resolve_many(kind="hero", ids=[1])

    assert second.entries[0].name_en == "Hero One"
    assert repository.calls == [("hero", 1), ("hero", 1)]


def test_catalog_version_uses_repository_metadata_without_reading_current_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DateTimeProbe:
        @staticmethod
        def fromisoformat(value: str) -> datetime:
            assert value == GENERATED_AT.isoformat()
            return GENERATED_AT

        @staticmethod
        def now(*args: object, **kwargs: object) -> datetime:
            raise AssertionError("resolver must not read the current clock")

    monkeypatch.setattr("app.vnext.catalog.resolver.datetime", DateTimeProbe)
    repository = FakeCatalogRepository()

    result = EntityNameResolver(repository).resolve_many(kind="hero", ids=[])

    assert result.catalog_version.generated_at == GENERATED_AT
    assert repository.metadata_calls == 1


def test_output_models_are_closed_strict_and_require_timezone() -> None:
    repository = FakeCatalogRepository()
    result = EntityNameResolver(repository).resolve_many(kind="hero", ids=[1])

    with pytest.raises(ValidationError):
        result.entries[0].__class__(
            id=True, status="found", name_en="x", name_zh=None
        )
    with pytest.raises(ValidationError):
        result.entries[0].__class__(
            id=1, status="found", name_en="x", name_zh=None, other="extra"
        )
    with pytest.raises(ValidationError):
        result.catalog_version.__class__(
            source="valve_dota2_datafeed",
            patch="x",
            generated_at=datetime(2026, 1, 1),
            schema_version=1,
        )


def test_real_local_catalog_records_match_all_three_entity_kinds() -> None:
    repository = DotaCatalogRepository()
    resolver = EntityNameResolver(repository)
    samples = [
        ("hero", repository.list_heroes()[0]),
        ("item", repository.list_items()[0]),
        ("ability", repository.list_abilities()[0]),
    ]

    for kind, record in samples:
        identifier = getattr(record, f"{kind}_id")
        resolved = resolver.resolve_many(kind=kind, ids=[identifier]).entries[0]  # type: ignore[arg-type]
        assert resolved.id == identifier
        assert resolved.status == "found"
        assert resolved.name_en == (record.name_en or None)
        assert resolved.name_zh == (record.name_zh or None)

    unknowns = resolver.resolve_many(kind="hero", ids=[0, 2**31 - 1])
    assert [entry.status for entry in unknowns.entries] == ["unknown", "unknown"]
    assert [(entry.name_en, entry.name_zh) for entry in unknowns.entries] == [
        (None, None),
        (None, None),
    ]
