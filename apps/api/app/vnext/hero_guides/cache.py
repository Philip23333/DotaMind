"""Redis-backed, whole-snapshot persistence for shared hero guide data."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBytes,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticSerializationError
from redis.exceptions import RedisError

from app.vnext.capabilities.hero.guide import HeroPosition, ProMatchExample, PubGuide

_SAMPLE_TYPES = ("pub", "pro")
_ERROR_CODES = {
    "d2pt_error",
    "timeout",
    "transport_error",
    "http_error",
    "response_too_large",
    "invalid_json",
    "invalid_response",
    "invalid_guide_data",
}
_HASH_FIELDS = {"snapshot", "last_attempt_at", "last_error"}
_HeroId = Annotated[StrictInt, Field(gt=0)]


class GuideCacheSnapshot(BaseModel):
    """Complete source and DTO snapshot for one Pub or Pro cache key."""

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        ser_json_bytes="base64",
        val_json_bytes="base64",
    )

    sample_type: Literal["pub", "pro"]
    hero_id: _HeroId
    position: HeroPosition | None
    retrieved_at: datetime
    content_type: StrictStr | None
    raw_body: StrictBytes
    source_rows: list[dict[str, JsonValue]]
    pub_guides: list[PubGuide] = Field(default_factory=list)
    pro_examples: list[ProMatchExample] = Field(default_factory=list)

    @field_validator("retrieved_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_partition_shape(self) -> GuideCacheSnapshot:
        if self.sample_type == "pub":
            if self.position is None:
                raise ValueError("Pub snapshots require a position")
            if self.pro_examples:
                raise ValueError("Pub snapshots cannot contain Pro examples")
        else:
            if self.position is not None:
                raise ValueError("Pro snapshots use a hero-wide key")
            if self.pub_guides:
                raise ValueError("Pro snapshots cannot contain Pub guides")
        return self


class HeroGuideWriter(Protocol):
    """Minimal persistence interface needed by the serial guide refresher."""

    async def publish(
        self,
        snapshot: GuideCacheSnapshot,
        *,
        attempted_at: datetime,
    ) -> None: ...

    async def record_failure(
        self,
        *,
        sample_type: Literal["pub", "pro"],
        hero_id: int,
        position: int | None = None,
        attempted_at: datetime,
        error_code: str,
    ) -> None: ...


class GuideCacheEntry(BaseModel):
    """The last good source snapshot and latest fetch-attempt outcome."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    snapshot: GuideCacheSnapshot | None = None
    last_attempt_at: datetime | None = None
    last_error: str | None = None

    @field_validator("last_attempt_at")
    @classmethod
    def require_timezone_when_present(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("last_attempt_at must include a timezone")
        return value


class HeroGuideCacheError(RuntimeError):
    """Base class for safe hero-guide cache errors."""


class HeroGuideCacheUnavailableError(HeroGuideCacheError):
    def __init__(self) -> None:
        super().__init__("hero guide cache is temporarily unavailable")


class HeroGuideCacheDataError(HeroGuideCacheError):
    def __init__(self) -> None:
        super().__init__("hero guide cache data is invalid")


class HeroGuideReader(Protocol):
    """Minimal read-only interface used by hero-guide queries."""

    async def get_pub(
        self,
        *,
        hero_id: int,
        position: int,
    ) -> GuideCacheEntry: ...

    async def get_pro(self, *, hero_id: int) -> GuideCacheEntry: ...


class RedisHeroGuideCache:
    """Persist independent Pub and Pro snapshots in Redis hashes without TTL."""

    KEY_PREFIX = "dotamind:vnext:hero-guide:v1"

    def __init__(self, client: Any) -> None:
        self._client = client

    async def get_pub(self, *, hero_id: int, position: int) -> GuideCacheEntry:
        _validate_hero_id(hero_id)
        _validate_position(position)
        return await self._get_entry(
            key=self._pub_key(hero_id, position),
            sample_type="pub",
            hero_id=hero_id,
            position=position,
        )

    async def get_pro(self, *, hero_id: int) -> GuideCacheEntry:
        _validate_hero_id(hero_id)
        return await self._get_entry(
            key=self._pro_key(hero_id),
            sample_type="pro",
            hero_id=hero_id,
            position=None,
        )

    async def publish(
        self,
        snapshot: GuideCacheSnapshot,
        *,
        attempted_at: datetime,
    ) -> None:
        if not isinstance(snapshot, GuideCacheSnapshot):
            raise ValueError("snapshot must be a GuideCacheSnapshot")
        _validate_aware_datetime(attempted_at, "attempted_at")

        try:
            checked_snapshot = _revalidate_snapshot(snapshot)
            serialized_snapshot = checked_snapshot.model_dump_json()
        except (ValidationError, PydanticSerializationError, TypeError, ValueError):
            raise HeroGuideCacheDataError() from None

        mapping = {
            "snapshot": serialized_snapshot,
            "last_attempt_at": attempted_at.isoformat(),
            "last_error": "",
        }
        key = self._snapshot_key(checked_snapshot)
        await self._hset(key, mapping)

    async def record_failure(
        self,
        *,
        sample_type: Literal["pub", "pro"],
        hero_id: int,
        position: int | None = None,
        attempted_at: datetime,
        error_code: str,
    ) -> None:
        key = self._partition_key(sample_type, hero_id, position)
        _validate_aware_datetime(attempted_at, "attempted_at")
        _validate_error_code(error_code)

        await self._hset(
            key,
            {
                "last_attempt_at": attempted_at.isoformat(),
                "last_error": error_code,
            },
        )

    async def _get_entry(
        self,
        *,
        key: str,
        sample_type: Literal["pub", "pro"],
        hero_id: int,
        position: int | None,
    ) -> GuideCacheEntry:
        try:
            raw_hash = await self._client.hgetall(key)
        except RedisError:
            raise HeroGuideCacheUnavailableError() from None
        return _decode_entry(
            raw_hash,
            sample_type=sample_type,
            hero_id=hero_id,
            position=position,
        )

    async def _hset(self, key: str, mapping: dict[str, str]) -> None:
        try:
            await self._client.hset(key, mapping=mapping)
        except RedisError:
            raise HeroGuideCacheUnavailableError() from None

    @classmethod
    def _pub_key(cls, hero_id: int, position: int) -> str:
        return f"{cls.KEY_PREFIX}:pub:{hero_id}:{position}"

    @classmethod
    def _pro_key(cls, hero_id: int) -> str:
        return f"{cls.KEY_PREFIX}:pro:{hero_id}"

    @classmethod
    def _snapshot_key(cls, snapshot: GuideCacheSnapshot) -> str:
        if snapshot.sample_type == "pub":
            assert snapshot.position is not None
            return cls._pub_key(snapshot.hero_id, snapshot.position)
        return cls._pro_key(snapshot.hero_id)

    @classmethod
    def _partition_key(
        cls,
        sample_type: Literal["pub", "pro"],
        hero_id: int,
        position: int | None,
    ) -> str:
        _validate_partition_identity(sample_type, hero_id, position)
        if sample_type == "pub":
            assert position is not None
            return cls._pub_key(hero_id, position)
        return cls._pro_key(hero_id)


def _decode_entry(
    raw_hash: object,
    *,
    sample_type: Literal["pub", "pro"],
    hero_id: int,
    position: int | None,
) -> GuideCacheEntry:
    if not isinstance(raw_hash, Mapping):
        raise HeroGuideCacheDataError()
    if not raw_hash:
        return GuideCacheEntry()

    fields: dict[str, str] = {}
    try:
        for raw_key, raw_value in raw_hash.items():
            key = _decode_redis_text(raw_key)
            value = _decode_redis_text(raw_value)
            if key in fields or key not in _HASH_FIELDS:
                raise HeroGuideCacheDataError()
            fields[key] = value
    except (UnicodeDecodeError, TypeError):
        raise HeroGuideCacheDataError() from None

    if not {"last_attempt_at", "last_error"}.issubset(fields):
        raise HeroGuideCacheDataError()
    if not set(fields).issubset(_HASH_FIELDS):
        raise HeroGuideCacheDataError()

    last_error = fields["last_error"]
    if last_error:
        try:
            _validate_error_code(last_error)
        except ValueError:
            raise HeroGuideCacheDataError() from None
    if "snapshot" not in fields and not last_error:
        raise HeroGuideCacheDataError()

    attempted_at = _parse_aware_datetime(fields["last_attempt_at"])
    snapshot = None
    if "snapshot" in fields:
        try:
            snapshot = GuideCacheSnapshot.model_validate_json(fields["snapshot"])
        except (ValidationError, ValueError, TypeError):
            raise HeroGuideCacheDataError() from None
        if (
            snapshot.sample_type != sample_type
            or snapshot.hero_id != hero_id
            or snapshot.position != position
        ):
            raise HeroGuideCacheDataError()

    return _validate_guide_cache_entry(
        GuideCacheEntry(
            snapshot=snapshot,
            last_attempt_at=attempted_at,
            last_error=last_error or None,
        ),
        sample_type=sample_type,
        hero_id=hero_id,
        position=position,
    )


def _decode_redis_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8")
    raise TypeError("Redis hash values must be text or bytes")


def _parse_aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise HeroGuideCacheDataError() from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HeroGuideCacheDataError()
    return parsed


def _validate_aware_datetime(value: object, field: str) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{field} must include a timezone")


def _validate_partition_identity(
    sample_type: object,
    hero_id: object,
    position: object,
) -> None:
    if type(sample_type) is not str or sample_type not in _SAMPLE_TYPES:
        raise ValueError("sample_type must be 'pub' or 'pro'")
    _validate_hero_id(hero_id)
    if sample_type == "pub":
        if position is None:
            raise ValueError("Pub failure records require a position")
        _validate_position(position)
    elif position is not None:
        raise ValueError("Pro failure records must not include a position")


def _validate_error_code(error_code: object) -> None:
    if type(error_code) is not str or error_code not in _ERROR_CODES:
        raise ValueError("error_code is not a supported D2PT error code")


def _revalidate_snapshot(snapshot: object) -> GuideCacheSnapshot:
    if not isinstance(snapshot, GuideCacheSnapshot):
        raise ValueError("snapshot must be a GuideCacheSnapshot")
    try:
        return GuideCacheSnapshot.model_validate(snapshot.model_dump(mode="python"))
    except (ValidationError, PydanticSerializationError, TypeError, ValueError):
        raise HeroGuideCacheDataError() from None


def _validate_guide_cache_entry(
    entry: object,
    *,
    sample_type: Literal["pub", "pro"],
    hero_id: int,
    position: int | None,
) -> GuideCacheEntry:
    if not isinstance(entry, GuideCacheEntry):
        raise HeroGuideCacheDataError()
    try:
        checked_entry = GuideCacheEntry.model_validate(entry.model_dump(mode="python"))
    except (ValidationError, PydanticSerializationError, TypeError, ValueError):
        raise HeroGuideCacheDataError() from None

    if checked_entry.last_error is not None:
        try:
            _validate_error_code(checked_entry.last_error)
        except ValueError:
            raise HeroGuideCacheDataError() from None
    if checked_entry != GuideCacheEntry():
        if checked_entry.last_attempt_at is None:
            raise HeroGuideCacheDataError()
        if checked_entry.snapshot is None and checked_entry.last_error is None:
            raise HeroGuideCacheDataError()
    if checked_entry.snapshot is not None and (
        checked_entry.snapshot.sample_type != sample_type
        or checked_entry.snapshot.hero_id != hero_id
        or checked_entry.snapshot.position != position
    ):
        raise HeroGuideCacheDataError()
    return checked_entry


def _validate_hero_id(hero_id: object) -> None:
    if type(hero_id) is not int or hero_id <= 0:
        raise ValueError("hero_id must be a positive integer")


def _validate_position(position: object) -> None:
    if type(position) is not int or not 1 <= position <= 5:
        raise ValueError("position must be an integer from 1 through 5")


__all__ = [
    "GuideCacheEntry",
    "GuideCacheSnapshot",
    "HeroGuideCacheDataError",
    "HeroGuideCacheError",
    "HeroGuideCacheUnavailableError",
    "HeroGuideReader",
    "HeroGuideWriter",
    "RedisHeroGuideCache",
]
