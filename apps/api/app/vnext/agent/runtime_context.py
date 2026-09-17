"""Read-only snapshots of the runtime state visible to the model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

CONVERGING_THRESHOLD = 4
TIME_PRESSURE_LIMITED_THRESHOLD = 0.40
TIME_PRESSURE_CRITICAL_THRESHOLD = 0.20


class RuntimePhase(str, Enum):
    EXPLORATION = "exploration"
    CONVERGING = "converging"


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
    def from_state(
        cls,
        *,
        current_step: int,
        max_steps: int,
        tools_available: bool = True,
        time_pressure: TimePressure = TimePressure.HEALTHY,
        context_pressure: ContextPressure = ContextPressure.NORMAL,
    ) -> RuntimeContext:
        """Build a snapshot from state already computed by one invocation."""

        remaining_turns = max_steps - current_step
        return cls(
            phase=_phase(remaining_turns, time_pressure),
            remaining_turns=remaining_turns,
            time_pressure=time_pressure,
            context_pressure=context_pressure,
            tools_available=tools_available,
        )


def classify_time_pressure(
    *,
    remaining_seconds: float | None,
    budget_seconds: float | None,
) -> TimePressure:
    if remaining_seconds is None or budget_seconds is None:
        return TimePressure.HEALTHY
    if budget_seconds <= 0:
        return TimePressure.CRITICAL

    ratio = max(0.0, remaining_seconds / budget_seconds)
    if ratio <= TIME_PRESSURE_CRITICAL_THRESHOLD:
        return TimePressure.CRITICAL
    if ratio <= TIME_PRESSURE_LIMITED_THRESHOLD:
        return TimePressure.LIMITED
    return TimePressure.HEALTHY


def _phase(
    remaining_turns: int | None,
    time_pressure: TimePressure,
) -> RuntimePhase:
    if remaining_turns is not None and remaining_turns <= CONVERGING_THRESHOLD:
        return RuntimePhase.CONVERGING
    if time_pressure in {TimePressure.LIMITED, TimePressure.CRITICAL}:
        return RuntimePhase.CONVERGING
    return RuntimePhase.EXPLORATION


__all__ = [
    "CONVERGING_THRESHOLD",
    "ContextPressure",
    "RuntimeContext",
    "RuntimePhase",
    "TIME_PRESSURE_CRITICAL_THRESHOLD",
    "TIME_PRESSURE_LIMITED_THRESHOLD",
    "TimePressure",
    "classify_time_pressure",
]
