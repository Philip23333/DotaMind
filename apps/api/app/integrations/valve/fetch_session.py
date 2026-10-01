"""Thread-safe response sharing and concurrency bounds for one Valve sync run."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from copy import deepcopy
from threading import BoundedSemaphore, Lock
from typing import Any

from app.integrations.valve.datafeed import ValveDatafeedClient


class ValveFetchSession:
    """Share each Datafeed request result within one bounded sync session."""

    def __init__(
        self,
        client: ValveDatafeedClient,
        *,
        max_concurrency: int = 8,
    ) -> None:
        if type(max_concurrency) is not int or not 1 <= max_concurrency <= 16:
            raise ValueError("max_concurrency must be an integer from 1 to 16")
        self._client = client
        self._semaphore = BoundedSemaphore(max_concurrency)
        self._lock = Lock()
        self._responses: dict[tuple[str, tuple[Any, ...]], Future[Any]] = {}

    def _request(
        self,
        method: str,
        client_call: Callable[..., dict[str, Any]],
        *args: Any,
    ) -> dict[str, Any]:
        key = (method, args)
        owner = False
        with self._lock:
            future = self._responses.get(key)
            if future is None:
                future = Future()
                self._responses[key] = future
                owner = True

        if owner:
            try:
                with self._semaphore:
                    response = client_call(*args)
                future.set_result(deepcopy(response))
            except BaseException as exc:
                future.set_exception(exc)

        return deepcopy(future.result())

    def patchnoteslist(self, language: str = "english") -> dict[str, Any]:
        return self._request("patchnoteslist", self._client.patchnoteslist, language)

    def patchnotes(
        self, version: str, language: str = "english"
    ) -> dict[str, Any]:
        return self._request("patchnotes", self._client.patchnotes, version, language)

    def herolist(self, language: str) -> dict[str, Any]:
        return self._request("herolist", self._client.herolist, language)

    def herodata(self, hero_id: int, language: str) -> dict[str, Any]:
        return self._request("herodata", self._client.herodata, hero_id, language)

    def abilitylist(self, language: str) -> dict[str, Any]:
        return self._request("abilitylist", self._client.abilitylist, language)

    def abilitydata(self, ability_id: int, language: str) -> dict[str, Any]:
        return self._request("abilitydata", self._client.abilitydata, ability_id, language)

    def itemlist(self, language: str) -> dict[str, Any]:
        return self._request("itemlist", self._client.itemlist, language)

    def itemdata(self, item_id: int, language: str) -> dict[str, Any]:
        return self._request("itemdata", self._client.itemdata, item_id, language)
