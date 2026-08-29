"""Provider-scoped opaque source locators for capability composition."""

from app.vnext.domain.common.models import DomainModel


class SourceLocator(DomainModel):
    """Locate one source object again without exposing its provider-private ID."""

    source: str
    kind: str
    value: str


__all__ = ["SourceLocator"]
