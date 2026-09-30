from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.vnext.capabilities.hero.guide import ProMatchExample, PubGuide
from app.vnext.hero_guides import file_cache
from app.vnext.hero_guides.cache import (
    GuideCacheEntry,
    GuideCacheSnapshot,
    HeroGuideCacheDataError,
    HeroGuideCacheUnavailableError,
)
from app.vnext.hero_guides.file_cache import (
    FileHeroGuideCache,
    GuideMigrationConflictError,
)
from app.vnext.providers.d2pt.parsers import parse_pro_examples, parse_pub_builds

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "d2pt"
_NOW = datetime(2026, 9, 28, 3, 0, tzinfo=UTC)
_ATTEMPTED = _NOW - timedelta(minutes=1)


def _run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def _snapshot(
    *,
    sample_type: str = "pub",
    hero_id: int = 18,
    position: int | None = 1,
    retrieved_at: datetime = _NOW,
    raw_body: bytes = b"[]",
    source_rows: list[dict[str, Any]] | None = None,
    pub_guides: list[PubGuide] | None = None,
    pro_examples: list[ProMatchExample] | None = None,
) -> GuideCacheSnapshot:
    return GuideCacheSnapshot(
        sample_type=sample_type,
        hero_id=hero_id,
        position=position,
        retrieved_at=retrieved_at,
        content_type="application/json",
        raw_body=raw_body,
        source_rows=[] if source_rows is None else source_rows,
        pub_guides=[] if pub_guides is None else pub_guides,
        pro_examples=[] if pro_examples is None else pro_examples,
    )


def _fixture_snapshot(
    filename: str,
    *,
    sample_type: str,
    hero_id: int,
    position: int | None,
) -> GuideCacheSnapshot:
    raw_body = (_FIXTURE_DIR / filename).read_bytes()
    source_rows = json.loads(raw_body)
    if sample_type == "pub":
        pub_guides = parse_pub_builds(source_rows, hero_id=hero_id, position=position)
        pro_examples: list[ProMatchExample] = []
    else:
        pub_guides = []
        pro_examples = parse_pro_examples(source_rows, hero_id=hero_id)
    return _snapshot(
        sample_type=sample_type,
        hero_id=hero_id,
        position=position,
        raw_body=raw_body,
        source_rows=source_rows,
        pub_guides=pub_guides,
        pro_examples=pro_examples,
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_sven_pub_and_pro_fixtures_round_trip_complete_entries(tmp_path: Path) -> None:
    cache = FileHeroGuideCache(tmp_path)
    pub = _fixture_snapshot(
        "pub_sven_pos1.json",
        sample_type="pub",
        hero_id=18,
        position=1,
    )
    pro = _fixture_snapshot(
        "pro_sven.json",
        sample_type="pro",
        hero_id=18,
        position=None,
    )

    _run(cache.publish(pub, attempted_at=_ATTEMPTED))
    _run(cache.publish(pro, attempted_at=_ATTEMPTED))
    pub_entry = _run(cache.get_pub(hero_id=18, position=1))
    pro_entry = _run(cache.get_pro(hero_id=18))

    assert pub_entry == GuideCacheEntry(
        snapshot=pub,
        last_attempt_at=_ATTEMPTED,
        last_error=None,
    )
    assert pro_entry == GuideCacheEntry(
        snapshot=pro,
        last_attempt_at=_ATTEMPTED,
        last_error=None,
    )
    pub_file = tmp_path / "guides" / "pub" / "18" / "1.json"
    pro_file = tmp_path / "guides" / "pro" / "18.json"
    pub_document = _read_json(pub_file)
    pro_document = _read_json(pro_file)
    assert set(pub_document) == {
        "schema_version",
        "sample_type",
        "hero_id",
        "position",
        "entry",
    }
    assert pub_document["entry"]["snapshot"]["raw_body"]
    assert pro_document["position"] is None
    assert pro_document["entry"]["snapshot"]["raw_body"]


@pytest.mark.parametrize(
    ("filename", "hero_id"),
    [
        ("pro_antimage.json", 1),
        ("pro_axe.json", 2),
        ("pro_crystal_maiden.json", 5),
    ],
)
def test_zero_ability_pro_fixtures_round_trip_exact_bytes_and_events(
    tmp_path: Path,
    filename: str,
    hero_id: int,
) -> None:
    snapshot = _fixture_snapshot(
        filename,
        sample_type="pro",
        hero_id=hero_id,
        position=None,
    )
    zero_count = sum(
        event.ability_id == 0
        for example in snapshot.pro_examples
        for event in example.ability_timeline
    )
    assert zero_count > 0
    cache = FileHeroGuideCache(tmp_path)

    _run(cache.publish(snapshot, attempted_at=_NOW))
    entry = _run(cache.get_pro(hero_id=hero_id))

    assert entry.snapshot is not None
    assert entry.snapshot.raw_body == snapshot.raw_body
    assert entry.snapshot.source_rows == snapshot.source_rows
    assert entry.snapshot.pro_examples == snapshot.pro_examples
    assert sum(
        event.ability_id == 0
        for example in entry.snapshot.pro_examples
        for event in example.ability_timeline
    ) == zero_count


def test_pub_positions_and_pro_hero_partition_are_independent(tmp_path: Path) -> None:
    cache = FileHeroGuideCache(tmp_path)
    pub_one = _snapshot(raw_body=b"pub-one")
    pub_two = _snapshot(position=2, raw_body=b"pub-two")
    pub_other_hero = _snapshot(hero_id=19, raw_body=b"pub-hero-19")
    pro = _snapshot(sample_type="pro", position=None, raw_body=b"pro")

    for snapshot in (pub_one, pub_two, pub_other_hero, pro):
        _run(cache.publish(snapshot, attempted_at=_NOW))

    assert _run(cache.get_pub(hero_id=18, position=1)).snapshot == pub_one
    assert _run(cache.get_pub(hero_id=18, position=2)).snapshot == pub_two
    assert _run(cache.get_pub(hero_id=19, position=1)).snapshot == pub_other_hero
    assert _run(cache.get_pro(hero_id=18)).snapshot == pro
    assert (tmp_path / "guides" / "pub" / "18" / "1.json").is_file()
    assert (tmp_path / "guides" / "pub" / "18" / "2.json").is_file()
    assert (tmp_path / "guides" / "pub" / "19" / "1.json").is_file()
    assert (tmp_path / "guides" / "pro" / "18.json").is_file()


def test_missing_partition_and_successful_empty_snapshot_are_distinct(tmp_path: Path) -> None:
    cache = FileHeroGuideCache(tmp_path)

    assert _run(cache.get_pub(hero_id=18, position=1)) == GuideCacheEntry()
    assert not (tmp_path / "guides").exists()
    empty = _snapshot(raw_body=b"[]", source_rows=[], pub_guides=[])
    _run(cache.publish(empty, attempted_at=_NOW))

    loaded = _run(cache.get_pub(hero_id=18, position=1))
    assert loaded.snapshot is not None
    assert loaded.snapshot == empty


def test_first_failure_and_failure_after_success_preserve_cache_semantics(
    tmp_path: Path,
) -> None:
    cache = FileHeroGuideCache(tmp_path)

    _run(
        cache.record_failure(
            sample_type="pub",
            hero_id=18,
            position=1,
            attempted_at=_NOW,
            error_code="timeout",
        )
    )
    first_failure = _run(cache.get_pub(hero_id=18, position=1))
    assert first_failure == GuideCacheEntry(
        snapshot=None,
        last_attempt_at=_NOW,
        last_error="timeout",
    )

    original = _snapshot(raw_body=b"previous-success", pub_guides=[PubGuide(build_id=4)])
    _run(cache.publish(original, attempted_at=_NOW + timedelta(minutes=1)))
    _run(
        cache.record_failure(
            sample_type="pub",
            hero_id=18,
            position=1,
            attempted_at=_NOW + timedelta(minutes=2),
            error_code="http_error",
        )
    )
    failed_after_success = _run(cache.get_pub(hero_id=18, position=1))
    assert failed_after_success.snapshot == original
    assert failed_after_success.last_attempt_at == _NOW + timedelta(minutes=2)
    assert failed_after_success.last_error == "http_error"

    repaired = _snapshot(raw_body=b"latest-success")
    _run(cache.publish(repaired, attempted_at=_NOW + timedelta(minutes=3)))
    after_success = _run(cache.get_pub(hero_id=18, position=1))
    assert after_success.snapshot == repaired
    assert after_success.last_attempt_at == _NOW + timedelta(minutes=3)
    assert after_success.last_error is None


@pytest.mark.parametrize(
    "damage",
    ["invalid_json", "wrong_schema", "outer_identity", "snapshot_identity", "bad_error"],
)
def test_corrupt_files_are_data_errors_without_source_payload_leaks(
    tmp_path: Path,
    damage: str,
) -> None:
    cache = FileHeroGuideCache(tmp_path)
    snapshot = _snapshot(raw_body=b"PRIVATE_SOURCE_BODY")
    _run(cache.publish(snapshot, attempted_at=_NOW))
    path = tmp_path / "guides" / "pub" / "18" / "1.json"
    original = path.read_bytes()

    if damage == "invalid_json":
        path.write_text('{"secret":"PRIVATE_SOURCE_BODY"', encoding="utf-8")
    else:
        payload = json.loads(original)
        if damage == "wrong_schema":
            payload["schema_version"] = 2
        elif damage == "outer_identity":
            payload["hero_id"] = 19
        elif damage == "snapshot_identity":
            payload["entry"]["snapshot"]["hero_id"] = 19
        else:
            payload["entry"]["last_error"] = "PRIVATE_SOURCE_BODY"
        _write_json(path, payload)
    damaged = path.read_bytes()

    with pytest.raises(HeroGuideCacheDataError) as raised:
        _run(cache.get_pub(hero_id=18, position=1))

    assert "PRIVATE_SOURCE_BODY" not in str(raised.value)
    assert path.read_bytes() == damaged


def test_file_identity_is_checked_against_pub_path(tmp_path: Path) -> None:
    cache = FileHeroGuideCache(tmp_path)
    _run(cache.publish(_snapshot(), attempted_at=_NOW))
    source_path = tmp_path / "guides" / "pub" / "18" / "1.json"
    target_path = tmp_path / "guides" / "pub" / "19" / "2.json"
    target_path.parent.mkdir(parents=True)
    target_path.write_bytes(source_path.read_bytes())

    with pytest.raises(HeroGuideCacheDataError):
        _run(cache.get_pub(hero_id=19, position=2))


def test_record_failure_refuses_to_overwrite_corrupt_file_but_publish_repairs_it(
    tmp_path: Path,
) -> None:
    cache = FileHeroGuideCache(tmp_path)
    _run(cache.publish(_snapshot(raw_body=b"first"), attempted_at=_NOW))
    path = tmp_path / "guides" / "pub" / "18" / "1.json"
    path.write_text("broken", encoding="utf-8")
    corrupted = path.read_bytes()

    with pytest.raises(HeroGuideCacheDataError):
        _run(
            cache.record_failure(
                sample_type="pub",
                hero_id=18,
                position=1,
                attempted_at=_NOW + timedelta(minutes=1),
                error_code="timeout",
            )
        )
    assert path.read_bytes() == corrupted

    replacement = _snapshot(raw_body=b"repaired")
    _run(cache.publish(replacement, attempted_at=_NOW + timedelta(minutes=2)))
    assert _run(cache.get_pub(hero_id=18, position=1)).snapshot == replacement


def test_unreadable_file_is_unavailable_and_non_file_target_is_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FileHeroGuideCache(tmp_path)
    _run(cache.publish(_snapshot(), attempted_at=_NOW))
    path = tmp_path / "guides" / "pub" / "18" / "1.json"
    original_read_bytes = Path.read_bytes

    def fail_read(target: Path) -> bytes:
        if target == path:
            raise PermissionError("private filesystem details")
        return original_read_bytes(target)

    monkeypatch.setattr(Path, "read_bytes", fail_read)
    with pytest.raises(HeroGuideCacheUnavailableError) as raised:
        _run(cache.get_pub(hero_id=18, position=1))
    assert "private filesystem details" not in str(raised.value)
    monkeypatch.undo()

    path.unlink()
    path.mkdir()
    with pytest.raises(HeroGuideCacheDataError):
        _run(cache.get_pub(hero_id=18, position=1))


def test_import_entry_is_lossless_idempotent_and_skips_empty_entry(tmp_path: Path) -> None:
    cache = FileHeroGuideCache(tmp_path)
    snapshot = _snapshot(raw_body=b"complete-source", source_rows=[{"nested": [0, False]}])
    entry = GuideCacheEntry(
        snapshot=snapshot,
        last_attempt_at=_NOW + timedelta(minutes=2),
        last_error="timeout",
    )

    assert _run(
        cache.import_entry(sample_type="pub", hero_id=18, position=1, entry=entry)
    ) is True
    assert _run(
        cache.import_entry(sample_type="pub", hero_id=18, position=1, entry=entry)
    ) is False
    assert _run(cache.get_pub(hero_id=18, position=1)) == entry

    assert _run(
        cache.import_entry(
            sample_type="pro",
            hero_id=18,
            entry=GuideCacheEntry(),
        )
    ) is False
    assert not (tmp_path / "guides" / "pro" / "18.json").exists()


def test_import_conflict_and_corrupt_target_never_overwrite_existing_file(
    tmp_path: Path,
) -> None:
    cache = FileHeroGuideCache(tmp_path)
    original = GuideCacheEntry(
        snapshot=_snapshot(raw_body=b"target"),
        last_attempt_at=_NOW,
    )
    incoming = GuideCacheEntry(
        snapshot=_snapshot(raw_body=b"source"),
        last_attempt_at=_NOW,
    )
    path = tmp_path / "guides" / "pub" / "18" / "1.json"
    assert _run(
        cache.import_entry(sample_type="pub", hero_id=18, position=1, entry=original)
    )
    original_bytes = path.read_bytes()

    with pytest.raises(GuideMigrationConflictError):
        _run(cache.import_entry(sample_type="pub", hero_id=18, position=1, entry=incoming))
    assert path.read_bytes() == original_bytes

    path.write_text("damaged target", encoding="utf-8")
    damaged_bytes = path.read_bytes()
    with pytest.raises(HeroGuideCacheDataError):
        _run(cache.import_entry(sample_type="pub", hero_id=18, position=1, entry=incoming))
    assert path.read_bytes() == damaged_bytes


def test_import_revalidates_mutated_model_before_writing(tmp_path: Path) -> None:
    cache = FileHeroGuideCache(tmp_path)
    invalid_snapshot = _snapshot(source_rows=[{"nested": {"value": 1}}])
    invalid_snapshot.source_rows[0]["nested"]["value"] = float("nan")
    entry = GuideCacheEntry(snapshot=invalid_snapshot, last_attempt_at=_NOW)

    with pytest.raises(HeroGuideCacheDataError):
        _run(cache.import_entry(sample_type="pub", hero_id=18, position=1, entry=entry))
    assert not (tmp_path / "guides").exists()


@pytest.mark.parametrize(
    "call",
    [
        lambda cache: cache.get_pub(hero_id=True, position=1),
        lambda cache: cache.get_pub(hero_id=18, position=True),
        lambda cache: cache.get_pub(hero_id=18, position=6),
        lambda cache: cache.get_pro(hero_id=0),
        lambda cache: cache.record_failure(
            sample_type="pub",
            hero_id=18,
            position=1,
            attempted_at=datetime(2026, 9, 28),
            error_code="timeout",
        ),
        lambda cache: cache.record_failure(
            sample_type="pub",
            hero_id=18,
            position=1,
            attempted_at=_NOW,
            error_code="unknown",
        ),
    ],
)
def test_invalid_inputs_fail_before_creating_files(tmp_path: Path, call: Any) -> None:
    cache = FileHeroGuideCache(tmp_path)

    with pytest.raises(ValueError):
        _run(call(cache))

    assert not (tmp_path / "guides").exists()


@pytest.mark.parametrize("failure", ["write", "replace"])
def test_failed_atomic_write_preserves_old_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    cache = FileHeroGuideCache(tmp_path)
    old = _snapshot(raw_body=b"old")
    new = _snapshot(raw_body=b"new")
    _run(cache.publish(old, attempted_at=_NOW))
    path = tmp_path / "guides" / "pub" / "18" / "1.json"
    original_bytes = path.read_bytes()

    if failure == "replace":
        def fail_replace(*_args: object) -> None:
            raise OSError("injected replace failure")

        monkeypatch.setattr(file_cache.os, "replace", fail_replace)
    else:
        original_fdopen = file_cache.os.fdopen

        class FailingWriter:
            def __init__(self, wrapped: Any) -> None:
                self.wrapped = wrapped

            def __enter__(self) -> FailingWriter:
                self.wrapped.__enter__()
                return self

            def __exit__(self, *args: object) -> object:
                return self.wrapped.__exit__(*args)

            def write(self, _value: bytes) -> None:
                raise OSError("injected write failure")

        monkeypatch.setattr(
            file_cache.os,
            "fdopen",
            lambda descriptor, mode: FailingWriter(original_fdopen(descriptor, mode)),
        )

    with pytest.raises(HeroGuideCacheUnavailableError):
        _run(cache.publish(new, attempted_at=_NOW + timedelta(minutes=1)))

    assert path.read_bytes() == original_bytes
    monkeypatch.undo()
    assert _run(cache.get_pub(hero_id=18, position=1)).snapshot == old
    assert not list(path.parent.glob("*.tmp"))


def test_atomic_replace_exposes_old_entry_before_and_new_entry_after(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FileHeroGuideCache(tmp_path)
    old = GuideCacheEntry(snapshot=_snapshot(raw_body=b"old"), last_attempt_at=_NOW)
    new = GuideCacheEntry(
        snapshot=_snapshot(raw_body=b"new"),
        last_attempt_at=_NOW + timedelta(minutes=1),
    )
    _run(cache.import_entry(sample_type="pub", hero_id=18, position=1, entry=old))
    original_replace = file_cache.os.replace
    observed: list[GuideCacheEntry] = []

    def inspect_replace(source: str | Path, destination: str | Path) -> None:
        before = cache._read_entry_sync("pub", 18, 1)
        assert before == old
        original_replace(source, destination)
        after = cache._read_entry_sync("pub", 18, 1)
        assert after == new
        observed.append(after)

    monkeypatch.setattr(file_cache.os, "replace", inspect_replace)
    _run(cache.publish(new.snapshot, attempted_at=new.last_attempt_at))
    assert observed == [new]


def test_reads_do_not_write_or_expire_files(tmp_path: Path) -> None:
    cache = FileHeroGuideCache(tmp_path)
    _run(cache.publish(_snapshot(), attempted_at=_NOW))
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in (tmp_path / "guides").rglob("*")
        if path.is_file()
    }

    for _ in range(3):
        _run(cache.get_pub(hero_id=18, position=1))
        _run(cache.get_pro(hero_id=18))

    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in (tmp_path / "guides").rglob("*")
        if path.is_file()
    }
    assert after == before


def test_snapshot_validation_errors_are_data_errors_before_file_io(tmp_path: Path) -> None:
    cache = FileHeroGuideCache(tmp_path)
    invalid = _snapshot(source_rows=[{"nested": {"value": 1}}])
    invalid.source_rows[0]["nested"]["value"] = float("nan")

    with pytest.raises(HeroGuideCacheDataError):
        _run(cache.publish(invalid, attempted_at=_NOW))
    assert not (tmp_path / "guides").exists()


def test_snapshot_model_still_rejects_invalid_field_types() -> None:
    with pytest.raises(ValidationError):
        _snapshot(sample_type="pro", position=1)
