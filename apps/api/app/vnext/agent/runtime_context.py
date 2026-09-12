"""Read-only snapshots of the runtime state visible to the model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

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
    def from_state(
        cls,
        *,
        current_step: int,
        max_steps: int,
        finalizing: bool,
        tools_available: bool,
        time_pressure: TimePressure = TimePressure.HEALTHY,
        context_pressure: ContextPressure = ContextPressure.NORMAL,
    ) -> RuntimeContext:
        """Build a snapshot from state already computed by one invocation."""

        remaining_turns = max_steps - current_step
        return cls(
            phase=_phase(finalizing, remaining_turns),
            remaining_turns=remaining_turns,
            time_pressure=time_pressure,
            context_pressure=context_pressure,
            tools_available=False if finalizing else tools_available,
        )


def _phase(finalizing: bool, remaining_turns: int | None) -> RuntimePhase:
    if finalizing:
        return RuntimePhase.FINALIZATION
    if remaining_turns is not None and remaining_turns <= CONVERGING_THRESHOLD:
        return RuntimePhase.CONVERGING
    return RuntimePhase.EXPLORATION


__all__ = [
    "CONVERGING_THRESHOLD",
    "ContextPressure",
    "RuntimeContext",
    "RuntimePhase",
    "TimePressure",
]
