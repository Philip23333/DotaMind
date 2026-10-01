from __future__ import annotations

from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Barrier, Event, Lock, local
from typing import Any

import pytest

from app.integrations.valve.fetch_session import ValveFetchSession


class RecordingClient:
    def __init__(self, responder=None) -> None:
        self.calls: Counter[tuple[str, tuple[Any, ...]]] = Counter()
        self._responder = responder

    def _call(self, method: str, *args: Any) -> dict[str, Any]:
        self.calls[(method, args)] += 1
        if self._responder is not None:
            return self._responder(method, *args)
        return {"method": method, "args": list(args), "nested": {"ids": [1, 2]}}

    def patchnoteslist(self, language: str = "english") -> dict[str, Any]:
        return self._call("patchnoteslist", language)

    def patchnotes(self, version: str, language: str = "english") -> dict[str, Any]:
        return self._call("patchnotes", version, language)

    def herolist(self, language: str) -> dict[str, Any]:
        return self._call("herolist", language)

    def herodata(self, hero_id: int, language: str) -> dict[str, Any]:
        return self._call("herodata", hero_id, language)

    def abilitylist(self, language: str) -> dict[str, Any]:
        return self._call("abilitylist", language)

    def abilitydata(self, ability_id: int, language: str) -> dict[str, Any]:
        return self._call("abilitydata", ability_id, language)

    def itemlist(self, language: str) -> dict[str, Any]:
        return self._call("itemlist", language)

    def itemdata(self, item_id: int, language: str) -> dict[str, Any]:
        return self._call("itemdata", item_id, language)


def test_explicit_methods_forward_all_request_parameters() -> None:
    client = RecordingClient()
    session = ValveFetchSession(client)

    session.patchnoteslist()
    session.patchnotes("7.41f", "schinese")
    session.herolist("english")
    session.herodata(1, "schinese")
    session.abilitylist("english")
    session.abilitydata(10, "schinese")
    session.itemlist("english")
    session.itemdata(2, "schinese")

    assert client.calls == Counter(
        {
            ("patchnoteslist", ("english",)): 1,
            ("patchnotes", ("7.41f", "schinese")): 1,
            ("herolist", ("english",)): 1,
            ("herodata", (1, "schinese")): 1,
            ("abilitylist", ("english",)): 1,
            ("abilitydata", (10, "schinese")): 1,
            ("itemlist", ("english",)): 1,
            ("itemdata", (2, "schinese")): 1,
        }
    )


def test_sequential_duplicate_requests_share_response_and_deep_copy() -> None:
    client = RecordingClient()
    session = ValveFetchSession(client)

    first = session.herolist("english")
    second = session.herolist("english")
    first["nested"]["ids"].append(3)
    second["nested"]["ids"].append(4)
    third = session.herolist("english")

    assert client.calls[("herolist", ("english",))] == 1
    assert second["nested"]["ids"] == [1, 2, 4]
    assert third["nested"]["ids"] == [1, 2]


def test_simultaneous_duplicate_requests_call_client_once() -> None:
    entered = Event()
    release = Event()
    client = RecordingClient(
        lambda method, language: (
            entered.set(),
            release.wait(timeout=3),
            {"method": method, "language": language, "rows": [{"id": 1}]},
        )[2]
    )
    session = ValveFetchSession(client)
    callers = 6
    ready = Barrier(callers + 1)

    def request() -> dict[str, Any]:
        ready.wait(timeout=3)
        return session.herolist("english")

    with ThreadPoolExecutor(max_workers=callers) as pool:
        futures = [pool.submit(request) for _ in range(callers)]
        ready.wait(timeout=3)
        assert entered.wait(timeout=3)
        release.set()
        results = [future.result(timeout=3) for future in futures]

    assert client.calls[("herolist", ("english",))] == 1
    assert results == [
        {"method": "herolist", "language": "english", "rows": [{"id": 1}]}
    ] * callers
    assert len({id(result) for result in results}) == callers


def test_request_parameters_are_part_of_the_cache_key() -> None:
    client = RecordingClient()
    session = ValveFetchSession(client)

    session.herolist("english")
    session.herolist("english")
    session.herolist("schinese")
    session.herodata(1, "english")
    session.herodata(2, "english")
    session.patchnotes("7.41e")
    session.patchnotes("7.41f")
    session.abilitylist("english")
    session.itemlist("english")

    assert client.calls[("herolist", ("english",))] == 1
    assert client.calls[("herolist", ("schinese",))] == 1
    assert client.calls[("herodata", (1, "english"))] == 1
    assert client.calls[("herodata", (2, "english"))] == 1
    assert client.calls[("patchnotes", ("7.41e", "english"))] == 1
    assert client.calls[("patchnotes", ("7.41f", "english"))] == 1
    assert client.calls[("abilitylist", ("english",))] == 1
    assert client.calls[("itemlist", ("english",))] == 1


def test_shared_semaphore_bounds_mixed_endpoint_peak_concurrency() -> None:
    lock = Lock()
    release = Event()
    two_started = Event()
    active = 0
    peak = 0

    def respond(method: str, *args: Any) -> dict[str, Any]:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 2:
                two_started.set()
        assert release.wait(timeout=3)
        with lock:
            active -= 1
        return {"method": method, "args": list(args)}

    client = RecordingClient(respond)
    session = ValveFetchSession(client, max_concurrency=2)
    calls = (
        lambda: session.herolist("english"),
        lambda: session.itemlist("english"),
        lambda: session.abilitylist("english"),
        lambda: session.patchnotes("7.41f"),
    )

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(call) for call in calls]
        assert two_started.wait(timeout=3)
        with lock:
            assert peak == 2
        release.set()
        [future.result(timeout=3) for future in futures]

    assert peak == 2


def test_duplicate_waiter_does_not_consume_slot_needed_by_unrelated_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hero_started = Event()
    unrelated_started = Event()
    release_hero = Event()
    duplicate_waiting = Event()
    duplicate_flag = local()
    client = RecordingClient()

    def blocking_call(method: str, *args: Any) -> dict[str, Any]:
        if method == "herolist":
            hero_started.set()
            assert release_hero.wait(timeout=3)
        else:
            unrelated_started.set()
        return {"method": method, "args": list(args)}

    client._responder = blocking_call
    session = ValveFetchSession(client, max_concurrency=2)
    original_result = Future.result
    shared_future: Future[Any] | None = None

    def observe_duplicate_wait(future: Future[Any], *args: Any, **kwargs: Any) -> Any:
        if future is shared_future and getattr(duplicate_flag, "active", False):
            duplicate_waiting.set()
        return original_result(future, *args, **kwargs)

    monkeypatch.setattr(Future, "result", observe_duplicate_wait)

    def duplicate_request() -> dict[str, Any]:
        duplicate_flag.active = True
        return session.herolist("english")

    with ThreadPoolExecutor(max_workers=3) as pool:
        owner = pool.submit(session.herolist, "english")
        assert hero_started.wait(timeout=3)
        shared_future = session._responses[("herolist", ("english",))]
        duplicate = pool.submit(duplicate_request)
        assert duplicate_waiting.wait(timeout=3)
        unrelated = pool.submit(session.itemlist, "english")
        assert unrelated_started.wait(timeout=3)
        release_hero.set()
        assert owner.result(timeout=3) == duplicate.result(timeout=3)
        assert unrelated.result(timeout=3)["method"] == "itemlist"

    assert client.calls[("herolist", ("english",))] == 1
    assert client.calls[("itemlist", ("english",))] == 1


def test_failure_is_cached_for_the_round_and_releases_concurrency_slot() -> None:
    client = RecordingClient(
        lambda method, *_args: (
            (_ for _ in ()).throw(RuntimeError("request failed"))
            if method == "herolist"
            else {"method": method}
        )
    )
    session = ValveFetchSession(client, max_concurrency=1)

    for _ in range(2):
        with pytest.raises(RuntimeError, match="request failed"):
            session.herolist("english")
    assert session.itemlist("english") == {"method": "itemlist"}
    assert client.calls[("herolist", ("english",))] == 1
    assert client.calls[("itemlist", ("english",))] == 1


def test_concurrent_waiters_receive_same_failure_without_retrying() -> None:
    entered = Event()
    release = Event()
    client = RecordingClient(
        lambda _method, _language: (
            entered.set(),
            release.wait(timeout=3),
            (_ for _ in ()).throw(RuntimeError("shared failure")),
        )[2]
    )
    session = ValveFetchSession(client)
    callers = 4
    ready = Barrier(callers + 1)

    def request() -> str:
        ready.wait(timeout=3)
        try:
            session.herolist("english")
        except RuntimeError as exc:
            return str(exc)
        raise AssertionError("request should fail")

    with ThreadPoolExecutor(max_workers=callers) as pool:
        futures = [pool.submit(request) for _ in range(callers)]
        ready.wait(timeout=3)
        assert entered.wait(timeout=3)
        release.set()
        assert [future.result(timeout=3) for future in futures] == [
            "shared failure"
        ] * callers

    assert client.calls[("herolist", ("english",))] == 1


def test_new_session_retries_the_same_request_with_a_new_client() -> None:
    client = RecordingClient()

    first = ValveFetchSession(client)
    second = ValveFetchSession(client)

    assert first.herolist("english") == second.herolist("english")
    assert client.calls[("herolist", ("english",))] == 2


@pytest.mark.parametrize("max_concurrency", [True, False, 0, -1, 17, 1.0, "2", None])
def test_invalid_max_concurrency_is_rejected(max_concurrency: object) -> None:
    with pytest.raises(ValueError, match="integer from 1 to 16"):
        ValveFetchSession(RecordingClient(), max_concurrency=max_concurrency)  # type: ignore[arg-type]
