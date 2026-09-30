"""Offline-import existing Redis hero-guide partitions into file storage."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.vnext.hero_guides.cache import (
    GuideCacheEntry,
    RedisHeroGuideCache,
    _validate_hero_id,
)
from app.vnext.hero_guides.file_cache import FileHeroGuideCache


@dataclass(frozen=True, slots=True)
class GuideMigrationReport:
    partitions_checked: int
    missing: int
    imported: int
    already_present: int


class GuideMigrationVerificationError(RuntimeError):
    """A file entry did not match the Redis entry after an import."""

    def __init__(self) -> None:
        super().__init__("hero guide migration read-back verification failed")


async def migrate_redis_guides(
    *,
    source: RedisHeroGuideCache,
    target: FileHeroGuideCache,
    hero_ids: Sequence[int],
) -> GuideMigrationReport:
    """Copy selected Redis partitions and verify each complete entry on disk."""

    ordered_hero_ids = _validated_unique_hero_ids(hero_ids)
    partitions_checked = 0
    missing = 0
    imported = 0
    already_present = 0

    for hero_id in ordered_hero_ids:
        for position in range(1, 6):
            entry = await source.get_pub(hero_id=hero_id, position=position)
            partitions_checked += 1
            if entry == GuideCacheEntry():
                missing += 1
                continue

            was_imported = await target.import_entry(
                sample_type="pub",
                hero_id=hero_id,
                position=position,
                entry=entry,
            )
            read_back = await target.get_pub(hero_id=hero_id, position=position)
            if read_back != entry:
                raise GuideMigrationVerificationError()
            if was_imported:
                imported += 1
            else:
                already_present += 1

        entry = await source.get_pro(hero_id=hero_id)
        partitions_checked += 1
        if entry == GuideCacheEntry():
            missing += 1
            continue

        was_imported = await target.import_entry(
            sample_type="pro",
            hero_id=hero_id,
            entry=entry,
        )
        read_back = await target.get_pro(hero_id=hero_id)
        if read_back != entry:
            raise GuideMigrationVerificationError()
        if was_imported:
            imported += 1
        else:
            already_present += 1

    return GuideMigrationReport(
        partitions_checked=partitions_checked,
        missing=missing,
        imported=imported,
        already_present=already_present,
    )


def _validated_unique_hero_ids(hero_ids: Sequence[int]) -> list[int]:
    if isinstance(hero_ids, (str, bytes, bytearray)) or not isinstance(hero_ids, Sequence):
        raise ValueError("hero_ids must be a sequence of positive integers")
    result: list[int] = []
    seen: set[int] = set()
    for hero_id in hero_ids:
        _validate_hero_id(hero_id)
        if hero_id not in seen:
            seen.add(hero_id)
            result.append(hero_id)
    return result


__all__ = [
    "GuideMigrationReport",
    "GuideMigrationVerificationError",
    "migrate_redis_guides",
]
