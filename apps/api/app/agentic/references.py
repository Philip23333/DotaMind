from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParsedReference:
    call_id: str
    path: str
    parts: tuple[str, ...]


def parse_reference(reference: str) -> ParsedReference | None:
    if not isinstance(reference, str) or not reference.startswith("$"):
        return None
    parts = tuple(part for part in reference.removeprefix("$").split(".") if part)
    if len(parts) < 2:
        return None
    return ParsedReference(call_id=parts[0], path=".".join(parts[1:]), parts=parts)


def lookup_path(value: Any, parts: tuple[str, ...]) -> tuple[Any, bool]:
    current = value
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        return None, False
    return current, True
