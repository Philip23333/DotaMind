from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any

import pytest

from app.integrations.valve.fetch_session import ValveFetchSession
from app.vnext.data_updates import refresh_all as refresh_all_module
from app.vnext.data_updates.catalog_refresh import CatalogRefreshReport
from app.vnext.data_updates.image_refresh import ImageRefreshFailure, ImageRefreshReport
from app.vnext.data_updates.patch_refresh import PatchRefreshReport
from app.vnext.hero_guides.refresh import HeroGuideRefreshReport
from app.vnext.providers.d2pt import D2PTResponse

_NOW = datetime(2026, 10, 1, 3, 0, tzinfo=UTC)


def _run_async(test: Any) -> Any:
    @wraps(test)
    def wrapper(*args: Any, **kwargs: Any) -> None:
        asyncio.run(test(*args, **kwargs))

    return wrapper


def _catalog_report(action: str = "updated") -> CatalogRefreshReport:
    return CatalogRefreshReport(
        action=action,  # type: ignore[arg-type]
        reason="patch_unchanged" if action == "skipped" else "patch_changed",
        previous_patch="7.41f",
        target_patch="7.41f",
        revision="a" * 32,
    )


def _patch_report(action: str = "updated") -> PatchRefreshReport:
    return PatchRefreshReport(
        action=action,  # type: ignore[arg-type]
        reason="already_present" if action == "skipped" else "missing",
        patch="7.41f",
        content_sha256="b" * 64,
        change_count=3,
    )


def _image_report(*, failures: tuple[ImageRefreshFailure, ...] = ()) -> ImageRefreshReport:
    return ImageRefreshReport(
        catalog_revision="a" * 32,
        catalog_patch="7.41f",
        target_count=2,
        downloaded=1 if failures else 0,
        skipped=1 if failures else 2,
        failures=failures,
    )


def _guide_report(status: str = "success") -> HeroGuideRefreshReport:
    return HeroGuideRefreshReport(
        status=status,  # type: ignore[arg-type]
        started_at=_NOW,
        finished_at=_NOW,
        hero_count=1,
        request_count=7,
        pub_published=5,
        pro_published=1,
        pub_empty=0,
        pro_empty=0,
        failures=[],
    )


@_run_async
async def test_catalog_patches_and_guides_start_together_images_wait_for_catalog_skip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()
    catalog_done = threading.Event()
    patches_started = threading.Event()
    guides_started = threading.Event()
    image_calls: list[dict[str, Any]] = []

    def catalog(**kwargs: Any) -> CatalogRefreshReport:
        assert kwargs["session"] is session
        assert patches_started.wait(timeout=3)
        assert guides_started.wait(timeout=3)
        catalog_done.set()
        return _catalog_report("skipped")

    def patches(**kwargs: Any) -> PatchRefreshReport:
        assert kwargs["session"] is session
        patches_started.set()
        return _patch_report("skipped")

    def images(**kwargs: Any) -> ImageRefreshReport:
        assert catalog_done.is_set()
        image_calls.append(kwargs)
        return _image_report()

    async def guides(**_kwargs: Any) -> refresh_all_module._Outcome:
        guides_started.set()
        return refresh_all_module._Outcome(report=_guide_report())

    monkeypatch.setattr(refresh_all_module, "refresh_catalog", catalog)
    monkeypatch.setattr(refresh_all_module, "refresh_patches", patches)
    monkeypatch.setattr(refresh_all_module, "refresh_images", images)
    monkeypatch.setattr(refresh_all_module, "_run_guides", guides)

    report = await refresh_all_module.refresh_all(
        data_root=tmp_path,
        session=session,  # type: ignore[arg-type]
        workers=3,
        image_workers=5,
        force=True,
        image_client=object(),  # type: ignore[arg-type]
        clock=lambda: _NOW,
    )

    assert list(report.modules) == ["catalog", "patches", "images", "guides"]
    assert report.modules["catalog"].status == "skipped"
    assert report.modules["patches"].status == "skipped"
    assert report.modules["images"].status == "success"
    assert report.modules["guides"].status == "success"
    assert report.status == "success" and report.exit_code == 0
    assert image_calls == [
        {
            "data_root": tmp_path,
            "workers": 5,
            "force": True,
            "client": image_calls[0]["client"],
        }
    ]


@_run_async
async def test_catalog_failure_blocks_images_but_patch_and_guides_continue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_called = False
    other_branches: list[str] = []

    def fail_catalog(**_kwargs: Any) -> CatalogRefreshReport:
        raise RuntimeError("secret response and private URL")

    def patches(**_kwargs: Any) -> PatchRefreshReport:
        other_branches.append("patches")
        return _patch_report()

    def images(**_kwargs: Any) -> ImageRefreshReport:
        nonlocal image_called
        image_called = True
        return _image_report()

    async def guides(**_kwargs: Any) -> refresh_all_module._Outcome:
        other_branches.append("guides")
        return refresh_all_module._Outcome(report=_guide_report())

    monkeypatch.setattr(refresh_all_module, "refresh_catalog", fail_catalog)
    monkeypatch.setattr(refresh_all_module, "refresh_patches", patches)
    monkeypatch.setattr(refresh_all_module, "refresh_images", images)
    monkeypatch.setattr(refresh_all_module, "_run_guides", guides)

    report = await refresh_all_module.refresh_all(
        data_root=tmp_path,
        session=object(),  # type: ignore[arg-type]
        clock=lambda: _NOW,
    )

    assert other_branches == ["guides", "patches"] or set(other_branches) == {
        "guides",
        "patches",
    }
    assert image_called is False
    assert report.modules["catalog"].status == "failed"
    assert report.modules["catalog"].reason == "operation_failed"
    assert report.modules["images"].status == "blocked"
    assert report.modules["images"].reason == "catalog_failed"
    assert report.modules["patches"].status == "success"
    assert report.modules["guides"].status == "success"
    assert report.status == "partial" and report.exit_code == 4
    assert "secret response" not in repr(report)


@_run_async
async def test_patch_or_guide_failure_does_not_cancel_other_refreshes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog_finished = threading.Event()
    image_finished = threading.Event()

    def catalog(**_kwargs: Any) -> CatalogRefreshReport:
        catalog_finished.set()
        return _catalog_report()

    def patches(**_kwargs: Any) -> PatchRefreshReport:
        raise RuntimeError("private provider response")

    def images(**_kwargs: Any) -> ImageRefreshReport:
        assert catalog_finished.is_set()
        image_finished.set()
        return _image_report(
            failures=(ImageRefreshFailure("heroes", 18, "download_failed"),)
        )

    async def guides(**_kwargs: Any) -> refresh_all_module._Outcome:
        return refresh_all_module._Outcome(report=_guide_report("failed"))

    monkeypatch.setattr(refresh_all_module, "refresh_catalog", catalog)
    monkeypatch.setattr(refresh_all_module, "refresh_patches", patches)
    monkeypatch.setattr(refresh_all_module, "refresh_images", images)
    monkeypatch.setattr(refresh_all_module, "_run_guides", guides)

    report = await refresh_all_module.refresh_all(
        data_root=tmp_path,
        session=object(),  # type: ignore[arg-type]
        clock=lambda: _NOW,
    )

    assert image_finished.is_set()
    assert report.modules["catalog"].status == "success"
    assert report.modules["patches"].status == "failed"
    assert report.modules["patches"].reason == "operation_failed"
    assert report.modules["images"].status == "partial"
    assert report.modules["images"].report == {
        "catalog_revision": "a" * 32,
        "catalog_patch": "7.41f",
        "target_count": 2,
        "downloaded": 1,
        "skipped": 1,
        "failures": (
            {"kind": "heroes", "entity_id": 18, "error_code": "download_failed"},
        ),
    }
    assert report.modules["guides"].status == "failed"
    assert report.status == "partial" and report.exit_code == 4


@_run_async
async def test_all_executable_modules_failed_returns_exit_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(**_kwargs: Any) -> Any:
        raise RuntimeError("secret")

    monkeypatch.setattr(refresh_all_module, "refresh_catalog", fail)
    monkeypatch.setattr(refresh_all_module, "refresh_patches", fail)

    async def guides(**_kwargs: Any) -> refresh_all_module._Outcome:
        return refresh_all_module._Outcome(reason="cache_unavailable")

    monkeypatch.setattr(refresh_all_module, "_run_guides", guides)

    report = await refresh_all_module.refresh_all(
        data_root=tmp_path,
        session=object(),  # type: ignore[arg-type]
        clock=lambda: _NOW,
    )

    assert report.modules["images"].status == "blocked"
    assert all(
        result.status in {"failed", "blocked"}
        for result in report.modules.values()
    )
    assert report.status == "failed" and report.exit_code == 1


class _BarrierDatafeed:
    def __init__(self) -> None:
        self.barrier = threading.Barrier(2)
        self.calls: list[str] = []
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0

    def _call(self, name: str) -> dict[str, Any]:
        with self.lock:
            self.calls.append(name)
            call_number = len(self.calls)
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            if call_number <= 2:
                self.barrier.wait(timeout=3)
            return {"name": name}
        finally:
            with self.lock:
                self.active -= 1

    def herolist(self, _language: str) -> dict[str, Any]:
        return self._call("herolist")

    def itemlist(self, _language: str) -> dict[str, Any]:
        return self._call("itemlist")

    def abilitylist(self, _language: str) -> dict[str, Any]:
        return self._call("abilitylist")


@_run_async
async def test_catalog_and_patches_share_session_cache_bound_force_and_workers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _BarrierDatafeed()
    session = ValveFetchSession(client, max_concurrency=2)  # type: ignore[arg-type]
    catalog_sessions: list[object] = []
    patch_sessions: list[object] = []
    catalog_options: list[dict[str, Any]] = []
    patch_options: list[dict[str, Any]] = []
    image_kwargs: list[dict[str, Any]] = []

    def catalog(**kwargs: Any) -> CatalogRefreshReport:
        catalog_sessions.append(kwargs["session"])
        catalog_options.append(kwargs)
        kwargs["session"].itemlist("english")
        kwargs["session"].herolist("english")
        return _catalog_report()

    def patches(**kwargs: Any) -> PatchRefreshReport:
        patch_sessions.append(kwargs["session"])
        patch_options.append(kwargs)
        kwargs["session"].abilitylist("english")
        kwargs["session"].herolist("english")
        return _patch_report()

    def images(**kwargs: Any) -> ImageRefreshReport:
        image_kwargs.append(kwargs)
        return _image_report()

    monkeypatch.setattr(refresh_all_module, "refresh_catalog", catalog)
    monkeypatch.setattr(refresh_all_module, "refresh_patches", patches)
    monkeypatch.setattr(refresh_all_module, "refresh_images", images)

    async def guides(**_kwargs: Any) -> refresh_all_module._Outcome:
        return refresh_all_module._Outcome(report=_guide_report())

    monkeypatch.setattr(refresh_all_module, "_run_guides", guides)
    report = await refresh_all_module.refresh_all(
        data_root=tmp_path,
        session=session,
        workers=2,
        image_workers=7,
        force=True,
        image_client=object(),  # type: ignore[arg-type]
        clock=lambda: _NOW,
    )

    assert catalog_sessions == [session]
    assert patch_sessions == [session]
    assert catalog_options[0]["workers"] == 2
    assert catalog_options[0]["force"] is True
    assert patch_options[0]["force"] is True
    assert client.calls.count("herolist") == 1
    assert set(client.calls) == {"herolist", "itemlist", "abilitylist"}
    assert client.peak == 2
    assert image_kwargs[0]["workers"] == 7
    assert image_kwargs[0]["force"] is True
    assert report.exit_code == 0


class _FakeGuideClient:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.active = 0
        self.peak = 0

    def _response(self, name: str, *args: Any, data: list[dict[str, Any]]) -> D2PTResponse:
        self.calls.append((name, *args))
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            raw = b"[]"
            return D2PTResponse(raw, data, _NOW, "application/json")
        finally:
            self.active -= 1

    def heroes_list(self) -> D2PTResponse:
        return self._response("heroes_list", data=[{"hero_id": 18}])

    def pub_builds(self, hero_id: int, position: int) -> D2PTResponse:
        return self._response("pub_builds", hero_id, position, data=[])

    def pro_builds(self, hero_id: int) -> D2PTResponse:
        return self._response("pro_builds", hero_id, data=[])


@_run_async
async def test_guides_reuse_serial_file_refresher_independently_of_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeGuideClient()
    monkeypatch.setattr(refresh_all_module, "refresh_catalog", lambda **_kwargs: _catalog_report())
    monkeypatch.setattr(refresh_all_module, "refresh_patches", lambda **_kwargs: _patch_report())
    monkeypatch.setattr(refresh_all_module, "refresh_images", lambda **_kwargs: _image_report())

    async def no_sleep(_duration: float) -> None:
        return None

    report = await refresh_all_module.refresh_all(
        data_root=tmp_path,
        session=object(),  # type: ignore[arg-type]
        force=True,
        guide_client=client,  # type: ignore[arg-type]
        guide_sleep=no_sleep,
        clock=lambda: _NOW,
    )

    assert client.calls == [
        ("heroes_list",),
        *( ("pub_builds", 18, position) for position in range(1, 6) ),
        ("pro_builds", 18),
    ]
    assert client.peak == 1
    assert report.modules["guides"].status == "success"
    assert report.modules["guides"].report is not None
    assert report.modules["guides"].report["request_count"] == 7
    assert (tmp_path / "guides" / "pub" / "18" / "1.json").is_file()


@_run_async
async def test_cancel_waits_for_started_threads_and_does_not_start_images(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_started = threading.Event()
    release_worker = threading.Event()
    image_called = False
    guide_started = asyncio.Event()
    guide_cleaned = asyncio.Event()

    def blocked_catalog(**_kwargs: Any) -> CatalogRefreshReport:
        worker_started.set()
        if not release_worker.wait(timeout=3):
            raise TimeoutError("test worker not released")
        return _catalog_report()

    def images(**_kwargs: Any) -> ImageRefreshReport:
        nonlocal image_called
        image_called = True
        return _image_report()

    monkeypatch.setattr(refresh_all_module, "refresh_catalog", blocked_catalog)
    monkeypatch.setattr(refresh_all_module, "refresh_patches", lambda **_kwargs: _patch_report())
    monkeypatch.setattr(refresh_all_module, "refresh_images", images)

    async def guides(**_kwargs: Any) -> refresh_all_module._Outcome:
        guide_started.set()
        try:
            await asyncio.Future()
        finally:
            guide_cleaned.set()
        return refresh_all_module._Outcome(report=_guide_report())

    monkeypatch.setattr(refresh_all_module, "_run_guides", guides)
    refresh_task = asyncio.create_task(
        refresh_all_module.refresh_all(data_root=tmp_path, session=object())  # type: ignore[arg-type]
    )
    await asyncio.to_thread(worker_started.wait, 3)
    await guide_started.wait()
    refresh_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await refresh_task
    assert image_called is False
    assert guide_cleaned.is_set()
    release_worker.set()
