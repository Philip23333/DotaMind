from app.integrations.stratz.heroes import StratzHeroes
from app.integrations.stratz.transport import (
    StratzGraphQLError,
    StratzHTTPStatusError,
    StratzTransport,
    StratzTransportError,
)


class StratzClient(StratzTransport):
    """Backward-compatible alias for older imports."""


__all__ = [
    "StratzClient",
    "StratzGraphQLError",
    "StratzHTTPStatusError",
    "StratzHeroes",
    "StratzTransport",
    "StratzTransportError",
]
