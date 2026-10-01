from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from app.vnext.data_updates import patch_refresh


def _records(
    patch: str = "7.41f",
    *,
    changes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "patch": patch,
        "released_at": "2026-09-15T07:00:00Z",
        "source_url": "https://www.dota2.com/patches/7.41f",
        "source_data_url": "https://www.dota2.com/data/patchnotes/7.41f",
        "normalization": "valve-patch-v1",
        "changes": [{"target": "hero:1", "kind": "buff"}] if changes is None else changes,
        "source_extension": {"retained": True},
    }


class FakeSession:
    pass


def _fake_valve(
    monkeypatch: pytest.MonkeyPatch,
    *,
    patch: str = "7.41f",
    records: dict[str, Any] | None = None,
) -> tuple[FakeSession, list[str], list[tuple[object, str]]]:
    session = FakeSession()
    latest_calls: list[str] = []
    build_calls: list[tuple[object, str]] = []

    def latest(actual_session: object) -> str:
        latest_calls.append("latest")
        if isinstance(patch, BaseException):
            raise patch
        return patch

    def build(actual_session: object, actual_patch: str) -> dict[str, Any]:
        build_calls.append((actual_session, actual_patch))
        if isinstance(records, BaseException):
            raise records
        return _records(actual_patch) if records is None else records

    monkeypatch.setattr(patch_refresh.game_data_sync, "_latest_patch", latest)
    monkeypatch.setattr(patch_refresh.game_data_sync, "_build_patch_records", build)
    return session, latest_calls, build_calls


def test_first_refresh_writes_legacy_patch_file_and_hashes_exact_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, latest_calls, build_calls = _fake_valve(monkeypatch)
    data_root = tmp_path / "data"

    report = patch_refresh.refresh_patches(data_root=data_root, session=session)

    path = data_root / "patches" / "7_41f.json"
    content = path.read_bytes()
    saved = json.loads(content)
    assert report.action == "updated"
    assert report.reason == "missing"
    assert report.patch == "7.41f"
    assert report.content_sha256 == hashlib.sha256(content).hexdigest()
    assert report.change_count == 1
    assert saved == _records()
    assert build_calls == [(session, "7.41f")]
    assert latest_calls == ["latest"]
    assert not (data_root / "catalog").exists()


def test_valid_same_patch_skips_without_rewriting_or_building(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    path = data_root / "patches" / "7_41f.json"
    path.parent.mkdir(parents=True)
    original = json.dumps(_records(), ensure_ascii=False, indent=2).encode() + b"\n"
    path.write_bytes(original)
    before = path.stat().st_mtime_ns
    session, _latest_calls, build_calls = _fake_valve(monkeypatch)

    report = patch_refresh.refresh_patches(data_root=data_root, session=session)

    assert report.action == "skipped"
    assert report.reason == "already_present"
    assert report.content_sha256 == hashlib.sha256(original).hexdigest()
    assert report.change_count == 1
    assert path.read_bytes() == original
    assert path.stat().st_mtime_ns == before
    assert build_calls == []


def test_force_rebuilds_and_new_patch_preserves_other_patch_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    older_path = data_root / "patches" / "7_41f.json"
    older_path.parent.mkdir(parents=True)
    older_path.write_text(json.dumps(_records("7.41f")), encoding="utf-8")
    old_bytes = older_path.read_bytes()

    session, _latest_calls, build_calls = _fake_valve(monkeypatch, patch="7.41g")
    report = patch_refresh.refresh_patches(data_root=data_root, session=session)
    assert report.reason == "missing"
    assert (data_root / "patches" / "7_41g.json").exists()
    assert older_path.read_bytes() == old_bytes

    session, _latest_calls, build_calls = _fake_valve(monkeypatch, patch="7.41g")
    report = patch_refresh.refresh_patches(
        data_root=data_root,
        session=session,
        force=True,
    )
    assert report.action == "updated"
    assert report.reason == "forced"
    assert build_calls == [(session, "7.41g")]
    assert older_path.read_bytes() == old_bytes


@pytest.mark.parametrize(
    "invalid_document",
    [
        [],
        {**_records(), "schema_version": True},
        {**_records(), "schema_version": 2},
        {**_records(), "patch": "7.41"},
        {**_records(), "released_at": "2026-09-15T07:00:00"},
        {**_records(), "source_url": None},
        {**_records(), "changes": {}},
        {**_records(), "changes": ["not-an-object"]},
        {**_records(), "extra": float("inf")},
    ],
)
def test_invalid_local_patch_record_is_rebuilt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_document: object,
) -> None:
    data_root = tmp_path / "data"
    path = data_root / "patches" / "7_41f.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(invalid_document, allow_nan=True), encoding="utf-8")
    session, _latest_calls, build_calls = _fake_valve(monkeypatch)

    report = patch_refresh.refresh_patches(data_root=data_root, session=session)

    assert report.action == "updated"
    assert report.reason == "invalid_local"
    assert json.loads(path.read_bytes()) == _records()
    assert build_calls == [(session, "7.41f")]


def test_valid_empty_changes_are_skipped_and_non_finite_json_is_repaired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    path = data_root / "patches" / "7_41f.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_records(changes=[])), encoding="utf-8")
    session, _latest_calls, build_calls = _fake_valve(
        monkeypatch,
        records=_records(changes=[]),
    )

    report = patch_refresh.refresh_patches(data_root=data_root, session=session)

    assert report.action == "skipped"
    assert report.change_count == 0
    assert build_calls == []

    path.write_text('{"schema_version":1,"patch":"7.41f","nested":[NaN]}', encoding="utf-8")
    session, _latest_calls, build_calls = _fake_valve(
        monkeypatch,
        records=_records(changes=[]),
    )
    repaired = patch_refresh.refresh_patches(data_root=data_root, session=session)
    assert repaired.reason == "invalid_local"
    assert repaired.change_count == 0
    assert build_calls == [(session, "7.41f")]


@pytest.mark.parametrize("invalid_patch", ["", "../7.41", "7.41/..", "7.41F", "７.４１", "7.41ff"])
def test_invalid_latest_patch_is_rejected_before_path_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_patch: str,
) -> None:
    session, _latest_calls, build_calls = _fake_valve(monkeypatch, patch=invalid_patch)

    with pytest.raises(patch_refresh.PatchRefreshError) as exc_info:
        patch_refresh.refresh_patches(data_root=tmp_path / "data", session=session)

    assert exc_info.value.reason == "invalid_patch"
    assert build_calls == []
    assert not (tmp_path / "data").exists()


def test_remote_failures_and_mismatched_records_do_not_write_and_retry_next_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    patch_dir = data_root / "patches"
    patch_dir.mkdir(parents=True)
    path = patch_dir / "7_41f.json"
    original = b"retain prior bytes"
    path.write_bytes(original)

    session, _, _ = _fake_valve(monkeypatch, patch=RuntimeError("private response"))
    with pytest.raises(RuntimeError, match="private response"):
        patch_refresh.refresh_patches(data_root=data_root, session=session)
    assert path.read_bytes() == original

    session, _, _ = _fake_valve(monkeypatch, records=_records("7.41e"))
    with pytest.raises(patch_refresh.PatchRefreshError) as exc_info:
        patch_refresh.refresh_patches(data_root=data_root, session=session)
    assert exc_info.value.reason == "invalid_patch_data"
    assert path.read_bytes() == original

    session, _, build_calls = _fake_valve(monkeypatch)
    report = patch_refresh.refresh_patches(data_root=data_root, session=session)
    assert report.reason == "invalid_local"
    assert build_calls == [(session, "7.41f")]


def test_builder_failure_does_not_mark_patch_present_for_next_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _, _ = _fake_valve(monkeypatch, records=RuntimeError("fetch failed"))
    with pytest.raises(RuntimeError):
        patch_refresh.refresh_patches(data_root=tmp_path / "data", session=session)
    assert not (tmp_path / "data" / "patches" / "7_41f.json").exists()

    session, _, build_calls = _fake_valve(monkeypatch)
    report = patch_refresh.refresh_patches(data_root=tmp_path / "data", session=session)
    assert report.action == "updated"
    assert build_calls == [(session, "7.41f")]


def test_generated_non_finite_data_is_rejected_without_replacing_existing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    path = data_root / "patches" / "7_41f.json"
    path.parent.mkdir(parents=True)
    original = json.dumps(_records()).encode("utf-8")
    path.write_bytes(original)
    invalid_records = _records()
    invalid_records["source_extension"] = {"number": float("nan")}
    session, _, _ = _fake_valve(monkeypatch, records=invalid_records)

    with pytest.raises(patch_refresh.PatchRefreshError) as exc_info:
        patch_refresh.refresh_patches(data_root=data_root, session=session, force=True)

    assert exc_info.value.reason == "invalid_patch_data"
    assert path.read_bytes() == original


def test_permission_error_is_not_treated_as_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_root = tmp_path / "data"
    path = data_root / "patches" / "7_41f.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"existing")
    original_read_bytes = Path.read_bytes
    session, _, build_calls = _fake_valve(monkeypatch)

    def denied_read(actual_path: Path) -> bytes:
        if actual_path == path:
            raise PermissionError("private path")
        return original_read_bytes(actual_path)

    monkeypatch.setattr(Path, "read_bytes", denied_read)
    with pytest.raises(patch_refresh.PatchRefreshError) as exc_info:
        patch_refresh.refresh_patches(data_root=data_root, session=session)

    assert exc_info.value.reason == "storage_error"
    assert build_calls == []


@pytest.mark.parametrize("failure", ["write", "replace"])
def test_atomic_write_failure_keeps_old_bytes_and_cleans_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    data_root = tmp_path / "data"
    patch_dir = data_root / "patches"
    patch_dir.mkdir(parents=True)
    path = patch_dir / "7_41f.json"
    original = b"old record bytes"
    path.write_bytes(original)
    session, _, _ = _fake_valve(monkeypatch)

    if failure == "write":
        actual_fdopen = os.fdopen

        class BrokenWriter:
            def __init__(self, descriptor: int, mode: str) -> None:
                self._file = actual_fdopen(descriptor, mode)

            def __enter__(self) -> BrokenWriter:
                return self

            def __exit__(self, *_args: object) -> None:
                self._file.close()

            def write(self, _content: bytes) -> int:
                raise OSError("disk full")

        monkeypatch.setattr(patch_refresh.os, "fdopen", BrokenWriter)
    else:
        monkeypatch.setattr(
            patch_refresh.os,
            "replace",
            lambda *_args: (_ for _ in ()).throw(OSError("replace failed")),
        )

    with pytest.raises(patch_refresh.PatchRefreshError) as exc_info:
        patch_refresh.refresh_patches(data_root=data_root, session=session, force=True)

    assert exc_info.value.reason == "storage_error"
    assert path.read_bytes() == original
    assert list(patch_dir.glob("*.tmp")) == []
