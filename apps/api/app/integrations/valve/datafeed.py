"""Small, testable transport for Valve's official Dota 2 Datafeed.

The client deliberately exposes a finite endpoint allow-list.  Sync code can
request only known Datafeed resources and cannot turn this class into a generic
URL fetcher or use it from the request path.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from enum import Enum
from json import JSONDecodeError
from time import sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DATAFEED_ROOT = "https://www.dota2.com/datafeed"
USER_AGENT = "DotaMind offline data sync/1.0"


class DatafeedEndpoint(str, Enum):
    HEROLIST = "herolist"
    HERODATA = "herodata"
    ABILITYLIST = "abilitylist"
    ABILITYDATA = "abilitydata"
    ITEMLIST = "itemlist"
    ITEMDATA = "itemdata"
    PATCHNOTESLIST = "patchnoteslist"
    PATCHNOTES = "patchnotes"


class ValveDatafeedClient:
    """Synchronous offline transport with bounded retries.

    ``opener`` and ``sleep_fn`` are injectable so fixture tests never need a
    network connection.  The public convenience methods accept IDs and
    locales, while ``fetch`` rejects unknown endpoints before constructing a
    URL.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 60.0,
        max_attempts: int = 3,
        retry_delays_seconds: tuple[float, ...] = (1.0, 2.0),
        opener: Callable[..., Any] = urlopen,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if len(retry_delays_seconds) < max_attempts - 1:
            raise ValueError("retry_delays_seconds must cover every retry")
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.retry_delays_seconds = retry_delays_seconds
        self._opener = opener
        self._sleep = sleep_fn

    def fetch(
        self,
        endpoint: DatafeedEndpoint | str,
        *,
        params: Mapping[str, str | int] | None = None,
    ) -> dict[str, Any]:
        endpoint_enum = self._coerce_endpoint(endpoint)
        query = {key: str(value) for key, value in (params or {}).items()}
        url = f"{DATAFEED_ROOT}/{endpoint_enum.value}"
        if query:
            url = f"{url}?{urlencode(query)}"
        request = Request(url, headers={"User-Agent": USER_AGENT})

        for attempt in range(self.max_attempts):
            try:
                with self._opener(request, timeout=self.timeout_seconds) as response:
                    payload = json.load(response)
                if not isinstance(payload, dict):
                    raise ValueError("Valve Datafeed response must be a JSON object")
                return payload
            except (OSError, URLError, HTTPError, JSONDecodeError):
                if attempt == self.max_attempts - 1:
                    raise
                self._sleep(self.retry_delays_seconds[attempt])
        raise AssertionError("unreachable")

    def herolist(self, language: str) -> dict[str, Any]:
        return self.fetch(DatafeedEndpoint.HEROLIST, params={"language": _language(language)})

    def herodata(self, hero_id: int, language: str) -> dict[str, Any]:
        return self.fetch(
            DatafeedEndpoint.HERODATA,
            params={"language": _language(language), "hero_id": _positive_id(hero_id)},
        )

    def abilitylist(self, language: str) -> dict[str, Any]:
        return self.fetch(DatafeedEndpoint.ABILITYLIST, params={"language": _language(language)})

    def abilitydata(self, ability_id: int, language: str) -> dict[str, Any]:
        return self.fetch(
            DatafeedEndpoint.ABILITYDATA,
            params={"language": _language(language), "ability_id": _positive_id(ability_id)},
        )

    def itemlist(self, language: str) -> dict[str, Any]:
        return self.fetch(DatafeedEndpoint.ITEMLIST, params={"language": _language(language)})

    def itemdata(self, item_id: int, language: str) -> dict[str, Any]:
        return self.fetch(
            DatafeedEndpoint.ITEMDATA,
            params={"language": _language(language), "item_id": _positive_id(item_id)},
        )

    def patchnoteslist(self, language: str = "english") -> dict[str, Any]:
        return self.fetch(
            DatafeedEndpoint.PATCHNOTESLIST,
            params={"language": _language(language)},
        )

    def patchnotes(self, version: str, language: str = "english") -> dict[str, Any]:
        version = str(version).strip()
        if not version or any(char not in "0123456789." for char in version):
            raise ValueError("version must contain only digits and dots")
        return self.fetch(
            DatafeedEndpoint.PATCHNOTES,
            params={"version": version, "language": _language(language)},
        )

    @staticmethod
    def _coerce_endpoint(endpoint: DatafeedEndpoint | str) -> DatafeedEndpoint:
        try:
            return (
                endpoint
                if isinstance(endpoint, DatafeedEndpoint)
                else DatafeedEndpoint(endpoint)
            )
        except ValueError as exc:
            raise ValueError(f"unsupported Valve Datafeed endpoint: {endpoint!r}") from exc


def _language(value: str) -> str:
    language = str(value).strip().lower()
    if language not in {"english", "schinese"}:
        raise ValueError("Valve Datafeed language must be 'english' or 'schinese'")
    return language


def _positive_id(value: int) -> int:
    identifier = int(value)
    if identifier <= 0:
        raise ValueError("Datafeed entity ID must be positive")
    return identifier
