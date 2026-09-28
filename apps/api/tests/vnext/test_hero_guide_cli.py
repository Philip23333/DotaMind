from __future__ import annotations

import asyncio
import importlib
import json
import multiprocessing
import os
import signal
import threading
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from redis.exceptions import RedisError

from app.vnext.hero_guides import cli
from app.vnext.hero_guides.cache import (
    HeroGuideCacheDataError,
    HeroGuideCacheUnavailableError,
)
from app.vnext.hero_guides.refresh import (
    HeroGuideRefreshFailure,
    HeroGuideRefreshReport,
)

_NOW = datetime(2026, 9, 28, 3, 0, tzinfo=UTC)


class FakeRedis:
    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.ping_calls = 0
        self.close_calls = 0
        self.ping_error: BaseException | None = None

    async def ping(self) -> bool:
        self.ping_calls += 1
        self.events.append("redis_ping")
        if self.ping_error is not None:
            raise self.ping_error
        return True

    async def aclose(self) -> None:
        self.close_calls += 1
        self.events.append("redis_close")


def _report(status: str = "success") -> HeroGuideRefreshReport:
    failures = (
        [HeroGuideRefreshFailure("pub", 18, 2, "timeout")]
        if status == "partial"
        else []
    )
    return HeroGuideRefreshReport(
        status=status,  # type: ignore[arg-type]
        started_at=_NOW,
        finished_at=_NOW,
        hero_count=1,
        request_count=7,
        pub_published=4,
        pro_published=1,
        pub_empty=2,
        pro_empty=0,
        failures=failures,
        heroes_error=None,
    )


def _install_fake_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    report: HeroGuideRefreshReport | None = None,
    refresher_error: BaseException | None = None,
    events: list[str] | None = None,
    from_url: Any | None = None,
    client_factory: Any | None = None,
    refresher_factory: Any | None = None,
) -> dict[str, list[Any]]:
    state: dict[str, list[Any]] = {"redis": [], "clients": [], "refreshers": []}
    shared_events = events if events is not None else []

    if from_url is None:
        def fake_from_url(url: str, *, decode_responses: bool) -> FakeRedis:
            shared_events.append("redis_create")
            assert url == "redis://fake"
            assert decode_responses is True
            redis_client = FakeRedis(shared_events)
            state["redis"].append(redis_client)
            return redis_client

        from_url = fake_from_url

    if client_factory is None:
        def fake_client_factory() -> object:
            shared_events.append("client_create")
            client = object()
            state["clients"].append(client)
            return client

        client_factory = fake_client_factory

    if refresher_factory is None:
        class FakeRefresher:
            def __init__(self, client: object, cache: object) -> None:
                shared_events.append("refresher_create")
                self.client = client
                self.cache = cache
                self.calls = 0
                state["refreshers"].append(self)

            async def refresh_all(self) -> HeroGuideRefreshReport:
                self.calls += 1
                shared_events.append("refresh")
                if refresher_error is not None:
                    raise refresher_error
                return _report() if report is None else report

        refresher_factory = FakeRefresher

    monkeypatch.setattr(cli, "from_url", from_url)
    monkeypatch.setattr(cli, "D2PTClient", client_factory)
    monkeypatch.setattr(cli, "HeroGuideRefresher", refresher_factory)
    return state


def _run_cli(
    *,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    status: str = "success",
) -> tuple[int, dict[str, Any], dict[str, list[Any]]]:
    state = _install_fake_runtime(monkeypatch, report=_report(status))
    stdout = StringIO()
    exit_code = cli.main(
        ["refresh"],
        environ={"DOTAMIND_REDIS_URL": "redis://fake"},
        lock_path=tmp_path / "refresh.lock",
        stdout=stdout,
    )
    return exit_code, json.loads(stdout.getvalue()), state


def _hold_lock(
    lock_path: str,
    acquired: Any,
    release: Any,
) -> None:
    fd = cli._try_acquire_lock(lock_path)
    if fd is None:
        acquired.set()
        return
    acquired.set()
    try:
        release.wait(10)
    finally:
        cli._release_lock(fd)


def test_no_subcommand_prints_help_and_returns_argument_error_without_resources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _install_fake_runtime(monkeypatch)
    output = StringIO()

    exit_code = cli.main([], environ={}, lock_path=tmp_path / "refresh.lock", stdout=output)

    assert exit_code == 2
    assert "usage:" in output.getvalue().lower()
    assert "refresh" in output.getvalue()
    assert state["redis"] == state["clients"] == state["refreshers"] == []
    assert not (tmp_path / "refresh.lock").exists()


@pytest.mark.parametrize("argv, expected_code", [(["--help"], 0), (["refresh", "--help"], 0)])
def test_help_does_not_create_clients_or_connect(
    argv: list[str],
    expected_code: int,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = _install_fake_runtime(monkeypatch)

    with pytest.raises(SystemExit) as exc_info:
        cli.main(argv, environ={}, lock_path=tmp_path / "refresh.lock")

    assert exc_info.value.code == expected_code
    assert "usage:" in capsys.readouterr().out.lower()
    assert state["redis"] == state["clients"] == state["refreshers"] == []
    assert not (tmp_path / "refresh.lock").exists()


@pytest.mark.parametrize("argv", [["unknown"], ["refresh", "--unknown"]])
def test_unknown_arguments_are_argparse_errors_without_connections(
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = _install_fake_runtime(monkeypatch)

    with pytest.raises(SystemExit) as exc_info:
        cli.main(argv, environ={}, lock_path=tmp_path / "refresh.lock")

    assert exc_info.value.code == 2
    assert "error:" in capsys.readouterr().err
    assert state["redis"] == state["clients"] == state["refreshers"] == []


def test_importing_package_main_module_does_not_start_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _install_fake_runtime(monkeypatch)

    imported = importlib.import_module("app.vnext.hero_guides.__main__")

    assert imported is not None
    assert state["redis"] == state["clients"] == state["refreshers"] == []


def test_missing_redis_url_fails_before_lock_or_d2pt_creation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _install_fake_runtime(monkeypatch)
    output = StringIO()

    exit_code = cli.main(
        ["refresh"],
        environ={},
        lock_path=tmp_path / "refresh.lock",
        stdout=output,
    )

    assert exit_code == 2
    assert json.loads(output.getvalue()) == {"status": "failed", "reason": "missing_redis_url"}
    assert state["redis"] == state["clients"] == state["refreshers"] == []
    assert not (tmp_path / "refresh.lock").exists()


def test_success_uses_one_resource_set_report_json_and_lock_before_redis(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "refresh.lock"
    events: list[str] = []
    state: dict[str, list[Any]] = {"redis": [], "clients": [], "refreshers": []}

    def fake_from_url(url: str, *, decode_responses: bool) -> FakeRedis:
        assert cli._try_acquire_lock(lock_path) is None
        events.append("redis_create")
        redis_client = FakeRedis(events)
        state["redis"].append(redis_client)
        return redis_client

    _install_fake_runtime(
        monkeypatch,
        report=_report(),
        events=events,
        from_url=fake_from_url,
        client_factory=lambda: _record_client(state, events),
        refresher_factory=lambda client, cache: _CountingRefresher(
            client,
            cache,
            report=_report(),
            state=state,
            events=events,
        ),
    )
    stdout = StringIO()

    exit_code = cli.main(
        ["refresh"],
        environ={"DOTAMIND_REDIS_URL": "redis://fake"},
        lock_path=lock_path,
        stdout=stdout,
    )

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["status"] == "success"
    assert set(payload["report"]) == {
        "status",
        "started_at",
        "finished_at",
        "hero_count",
        "request_count",
        "pub_published",
        "pro_published",
        "pub_empty",
        "pro_empty",
        "failures",
        "heroes_error",
    }
    assert payload["report"]["started_at"].endswith("+00:00")
    assert payload["report"]["failures"] == []
    assert len(stdout.getvalue().splitlines()) == 1
    assert len(state["redis"]) == len(state["clients"]) == len(state["refreshers"]) == 1
    assert state["redis"][0].ping_calls == 1
    assert state["redis"][0].close_calls == 1
    assert state["refreshers"][0].calls == 1
    assert events.index("redis_create") < events.index("redis_ping")
    assert events.index("redis_ping") < events.index("client_create")
    assert events.index("client_create") < events.index("refresher_create")
    assert events.index("refresher_create") < events.index("refresh")
    assert events.index("refresh") < events.index("redis_close")
    assert lock_path.exists()
    probe_fd = cli._try_acquire_lock(lock_path)
    assert probe_fd is not None
    cli._release_lock(probe_fd)


class _CountingRefresher:
    def __init__(
        self,
        client: object,
        cache: object,
        *,
        report: HeroGuideRefreshReport,
        state: dict[str, list[Any]],
        events: list[str],
    ) -> None:
        self.client = client
        self.cache = cache
        self.report = report
        self.calls = 0
        self.events = events
        state["refreshers"].append(self)
        self.events.append("refresher_create")

    async def refresh_all(self) -> HeroGuideRefreshReport:
        self.calls += 1
        self.events.append("refresh")
        return self.report


def _record_client(state: dict[str, list[Any]], events: list[str]) -> object:
    events.append("client_create")
    client = object()
    state["clients"].append(client)
    return client


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [("success", 0), ("partial", 4), ("failed", 1)],
)
def test_report_status_maps_to_fixed_exit_codes(
    status: str,
    expected_exit: int,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    exit_code, payload, state = _run_cli(monkeypatch=monkeypatch, tmp_path=tmp_path, status=status)

    assert exit_code == expected_exit
    assert payload["status"] == status
    assert payload["report"]["status"] == status
    assert len(payload["report"]["failures"]) == (1 if status == "partial" else 0)
    assert len(state["refreshers"]) == 1


def test_redis_ping_failure_closes_client_and_redacts_exception(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    redis_client = FakeRedis()
    redis_client.ping_error = RedisError("REDIS_URL_SECRET")
    state: dict[str, list[Any]] = {"redis": [redis_client], "clients": [], "refreshers": []}
    monkeypatch.setattr(
        cli,
        "from_url",
        lambda url, *, decode_responses: redis_client,
    )
    monkeypatch.setattr(cli, "D2PTClient", lambda: state["clients"].append(object()))
    output = StringIO()

    exit_code = cli.main(
        ["refresh"],
        environ={"DOTAMIND_REDIS_URL": "redis://user:secret@host"},
        lock_path=tmp_path / "refresh.lock",
        stdout=output,
    )

    assert exit_code == 1
    assert json.loads(output.getvalue()) == {"status": "failed", "reason": "redis_unavailable"}
    assert "REDIS_URL_SECRET" not in output.getvalue()
    assert "user:secret" not in output.getvalue()
    assert redis_client.ping_calls == 1
    assert redis_client.close_calls == 1
    assert state["clients"] == []


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (HeroGuideCacheUnavailableError(), "cache_unavailable"),
        (HeroGuideCacheDataError(), "cache_invalid_data"),
        (RuntimeError("PRIVATE_TRACEBACK"), "refresh_failed"),
    ],
)
def test_refresh_and_cache_errors_use_safe_failure_codes(
    error: BaseException,
    reason: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fake_runtime(monkeypatch, refresher_error=error)
    output = StringIO()

    exit_code = cli.main(
        ["refresh"],
        environ={"DOTAMIND_REDIS_URL": "redis://fake"},
        lock_path=tmp_path / "refresh.lock",
        stdout=output,
    )

    assert exit_code == 1
    assert json.loads(output.getvalue()) == {"status": "failed", "reason": reason}
    assert "PRIVATE_TRACEBACK" not in output.getvalue()
    assert "redis://fake" not in output.getvalue()


def test_lock_system_error_is_not_misreported_as_already_running(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _install_fake_runtime(monkeypatch)
    output = StringIO()

    exit_code = cli.main(
        ["refresh"],
        environ={"DOTAMIND_REDIS_URL": "redis://fake"},
        lock_path=tmp_path / "missing" / "refresh.lock",
        stdout=output,
    )

    assert exit_code == 1
    assert json.loads(output.getvalue()) == {"status": "failed", "reason": "lock_unavailable"}
    assert state["redis"] == state["clients"] == state["refreshers"] == []


def test_second_linux_process_is_skipped_then_can_run_without_deleting_lock_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "shared.lock"
    context = multiprocessing.get_context("fork")
    acquired = context.Event()
    release = context.Event()
    process = context.Process(target=_hold_lock, args=(str(lock_path), acquired, release))
    process.start()
    assert acquired.wait(5)
    state = _install_fake_runtime(monkeypatch)
    skipped_output = StringIO()

    skipped_code = cli.main(
        ["refresh"],
        environ={"DOTAMIND_REDIS_URL": "redis://fake"},
        lock_path=lock_path,
        stdout=skipped_output,
    )

    assert skipped_code == 3
    assert json.loads(skipped_output.getvalue()) == {
        "status": "skipped",
        "reason": "already_running",
    }
    assert state["redis"] == state["clients"] == state["refreshers"] == []
    release.set()
    process.join(5)
    assert process.exitcode == 0
    assert lock_path.exists()

    run_output = StringIO()
    run_code = cli.main(
        ["refresh"],
        environ={"DOTAMIND_REDIS_URL": "redis://fake"},
        lock_path=lock_path,
        stdout=run_output,
    )
    assert run_code == 0
    assert json.loads(run_output.getvalue())["status"] == "success"
    assert lock_path.exists()
    probe_fd = cli._try_acquire_lock(lock_path)
    assert probe_fd is not None
    cli._release_lock(probe_fd)


@pytest.mark.parametrize("stop_signal", [signal.SIGINT, signal.SIGTERM])
def test_cancel_waits_for_worker_before_redis_close_and_lock_release(
    stop_signal: signal.Signals,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "cancel.lock"
    worker_started = threading.Event()
    release_worker = threading.Event()
    worker_finished = threading.Event()
    executor_shutdown = threading.Event()
    lock_held_during_cleanup: list[bool] = []
    errors: list[BaseException] = []
    events: list[str] = []
    redis_client = FakeRedis(events)
    refreshers: list[Any] = []
    clients: list[Any] = []
    monkeypatch.setattr(cli, "from_url", lambda url, *, decode_responses: redis_client)
    monkeypatch.setattr(cli, "D2PTClient", lambda: clients.append(object()) or clients[-1])

    def blocking_request() -> None:
        worker_started.set()
        events.append("worker_started")
        release_worker.wait(10)
        worker_finished.set()
        events.append("worker_finished")

    class BlockingRefresher:
        def __init__(self, client: object, cache: object) -> None:
            self.calls = 0
            self.continued_after_request = False
            refreshers.append(self)

        async def refresh_all(self) -> HeroGuideRefreshReport:
            self.calls += 1
            await asyncio.to_thread(blocking_request)
            self.continued_after_request = True
            return _report()

    monkeypatch.setattr(cli, "HeroGuideRefresher", BlockingRefresher)

    probe_loop = asyncio.new_event_loop()
    loop_type = type(probe_loop)
    probe_loop.close()
    original_shutdown = loop_type.shutdown_default_executor

    async def observed_shutdown(
        loop: asyncio.AbstractEventLoop,
        timeout: float | None = None,
    ) -> None:
        executor_shutdown.set()
        await original_shutdown(loop, timeout)

    monkeypatch.setattr(loop_type, "shutdown_default_executor", observed_shutdown)

    def signal_controller() -> None:
        try:
            if not worker_started.wait(5):
                raise AssertionError("request worker did not start")
            os.kill(os.getpid(), stop_signal)
            if not executor_shutdown.wait(5):
                raise AssertionError("executor cleanup did not start")
            probe_fd = cli._try_acquire_lock(lock_path)
            lock_held_during_cleanup.append(probe_fd is None)
            if probe_fd is not None:
                cli._release_lock(probe_fd)
            os.kill(os.getpid(), stop_signal)
            release_worker.set()
        except BaseException as exc:
            errors.append(exc)
            release_worker.set()

    controller = threading.Thread(target=signal_controller, daemon=True)
    controller.start()
    output = StringIO()
    exit_code = cli.main(
        ["refresh"],
        environ={"DOTAMIND_REDIS_URL": "redis://fake"},
        lock_path=lock_path,
        stdout=output,
    )
    controller.join(5)

    assert not controller.is_alive()
    assert errors == []
    assert exit_code == 130
    assert json.loads(output.getvalue()) == {"status": "cancelled"}
    assert len(refreshers) == len(clients) == 1
    assert refreshers[0].calls == 1
    assert refreshers[0].continued_after_request is False
    assert lock_held_during_cleanup == [True]
    assert worker_finished.is_set()
    assert redis_client.close_calls == 1
    assert events.index("worker_finished") < events.index("redis_close")
    assert lock_path.exists()
    probe_fd = cli._try_acquire_lock(lock_path)
    assert probe_fd is not None
    cli._release_lock(probe_fd)
