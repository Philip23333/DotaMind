"""Provider-scoped opaque source locators for capability composition."""

from app.vnext.domain.common.models import DomainModel


class SourceLocator(DomainModel):
    """Locate one source object again without exposing its provider-private ID."""

    source: str
    kind: str
    value: str


class SourceLocatorError(ValueError):
    """A source locator is malformed, unsupported, or no longer known."""

    def __init__(self, message: str, *, details: dict[str, str]) -> None:
        super().__init__(message)
        self.details = details


__all__ = ["SourceLocator", "SourceLocatorError"]
