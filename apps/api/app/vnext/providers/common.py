"""Internal provider fetch metadata shared by HTTP adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class ProviderBatch(Generic[T]):
    items: list[T]
    fetched_at: datetime
    has_more: bool | None = None


@dataclass(frozen=True, slots=True)
class ProviderObject(Generic[T]):
    item: T
    fetched_at: datetime


__all__ = ["ProviderBatch", "ProviderObject"]
