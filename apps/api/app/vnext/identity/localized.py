"""Provider-neutral localized catalog identities for versioned artifacts."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LocalizedName:
    """Available canonical English and Chinese catalog display names."""

    name_en: str | None = None
    name_zh: str | None = None


__all__ = ["LocalizedName"]
