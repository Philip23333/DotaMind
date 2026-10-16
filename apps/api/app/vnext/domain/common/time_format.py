"""Shared game-time and duration display without changing numeric precision."""

from decimal import Decimal
from math import isfinite


def format_game_time(seconds: int | float | None) -> str | None:
    """Return signed MM:SS[.fraction], with unbounded total minutes."""
    if seconds is None:
        return None
    if type(seconds) not in (int, float):
        raise TypeError("Game time must be numeric seconds or None")
    if isinstance(seconds, float) and not isfinite(seconds):
        raise ValueError("Game time must be finite")

    # Expanding the decimal representation avoids rounding fractional seconds
    # or displaying a binary floating-point remainder after division by 60.
    magnitude = format(Decimal(str(seconds)).copy_abs(), "f")
    whole, _, fraction = magnitude.partition(".")
    minutes, remainder = divmod(int(whole), 60)
    suffix = fraction.rstrip("0")
    sign = "-" if seconds < 0 else ""
    return f"{sign}{minutes:02d}:{remainder:02d}" + (f".{suffix}" if suffix else "")
