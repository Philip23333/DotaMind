"""Read-only snapshots of the runtime state visible to the model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

CONVERGING_THRESHOLD = 4


class RuntimePhase(str, Enum):
    EXPLORATION = "exploration"
    CONVERGING = "converging"
    FINALIZATION = "finalization"


class TimePressure(str, Enum):
    HEALTHY = "healthy"
    LIMITED = "limited"
    CRITICAL = "critical"


class ContextPressure(str, Enum):
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class RuntimeContext:
    """Ephemeral model-visible state captured from one runtime invocation."""

    phase: RuntimePhase
    remaining_turns: int | None
    time_pressure: TimePressure
    context_pressure: ContextPressure
    tools_available: bool

    @classmethod
    def from_runtime(cls, runtime: Any) -> RuntimeContext:
        """Capture runtime state without changing the runtime or its controls."""

        finalizing = bool(getattr(runtime, "finalizing", False))
        remaining_turns = _remaining_turns(runtime)
        phase = _phase(finalizing, remaining_turns)
        return cls(
            phase=phase,
            remaining_turns=remaining_turns,
            time_pressure=_time_pressure(runtime),
            context_pressure=ContextPressure.NORMAL,
            tools_available=False if finalizing else _tools_available(runtime),
        )


def _phase(finalizing: bool, remaining_turns: int | None) -> RuntimePhase:
    if finalizing:
        return RuntimePhase.FINALIZATION
    if remaining_turns is not None and remaining_turns <= CONVERGING_THRESHOLD:
        return RuntimePhase.CONVERGING
    return RuntimePhase.EXPLORATION


def _remaining_turns(runtime: Any) -> int | None:
    direct_value = getattr(runtime, "remaining_turns", None)
    if direct_value is not None:
        return int(direct_value)

    limits = getattr(runtime, "limits", None)
    max_steps = getattr(runtime, "max_steps", None)
    if max_steps is None and limits is not None:
        max_steps = getattr(limits, "max_steps", None)

    current_step = getattr(runtime, "current_step", None)
    if current_step is None:
        current_step = getattr(runtime, "step", None)
    if max_steps is None or current_step is None:
        return None
    return int(max_steps) - int(current_step)


def _time_pressure(runtime: Any) -> TimePressure:
    value = getattr(runtime, "time_pressure", None)
    if value is None:
        return TimePressure.HEALTHY
    if isinstance(value, TimePressure):
        return value
    return TimePressure(str(value).lower())


def _tools_available(runtime: Any) -> bool:
    for attribute in ("tools_available", "tools_enabled"):
        value = getattr(runtime, attribute, None)
        if value is not None:
            return bool(value)
    return True


__all__ = [
    "CONVERGING_THRESHOLD",
    "ContextPressure",
    "RuntimeContext",
    "RuntimePhase",
    "TimePressure",
]
