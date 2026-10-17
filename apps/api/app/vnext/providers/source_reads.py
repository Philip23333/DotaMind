"""Reuse validated source reads within one application request only."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, TypeVar

logger = logging.getLogger(__name__)
_T = TypeVar("_T")
_ReadKey = tuple[object, str, int | None]


@dataclass
class SourceReadCache:
    """Successful values and per-key locks; no background tasks or failure cache."""

    remote_reads: int = 0
    cache_hits: int = 0
    _values: dict[_ReadKey, Any] = field(default_factory=dict, repr=False)
    _locks: dict[_ReadKey, asyncio.Lock] = field(default_factory=dict, repr=False)

    async def read(self, key: _ReadKey, fetch: Callable[[], Awaitable[_T]]) -> _T:
        async with self._locks.setdefault(key, asyncio.Lock()):
            if key in self._values:
                self.cache_hits += 1
                return deepcopy(self._values[key])
            self.remote_reads += 1
            value = await fetch()
            self._values[key] = deepcopy(value)
            return deepcopy(value)

    def clear(self) -> None:
        self._values.clear()
        self._locks.clear()


_active_cache: ContextVar[SourceReadCache | None] = ContextVar("source_read_cache", default=None)


@contextmanager
def source_read_scope() -> Iterator[SourceReadCache]:
    """Own a fresh cache for one run; always discard it on completion or failure."""

    cache = SourceReadCache()
    token = _active_cache.set(cache)
    try:
        yield cache
    finally:
        _active_cache.reset(token)
        logger.info(
            "Source reads finished: remote_reads=%s cache_hits=%s",
            cache.remote_reads,
            cache.cache_hits,
        )
        cache.clear()


async def read_source(
    owner: object,
    operation: str,
    identity: int | None,
    fetch: Callable[[], Awaitable[_T]],
) -> _T:
    """Keep adapter instances/configurations isolated; validate before caching."""

    cache = _active_cache.get()
    if cache is None:
        return await fetch()
    return await cache.read((owner, operation, identity), fetch)
