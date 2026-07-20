import time
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    def now_utc(self) -> datetime: ...

    def monotonic(self) -> float: ...


class SystemClock:
    def now_utc(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()


@dataclass
class FakeClock:
    """Deterministic injectable clock for runtime and trace contract tests."""

    current_utc: datetime
    current_monotonic: float = 0.0

    def __post_init__(self) -> None:
        if self.current_utc.tzinfo is None or self.current_utc.utcoffset() is None:
            raise ValueError("FakeClock current_utc must be timezone-aware")
        self.current_utc = self.current_utc.astimezone(timezone.utc)

    def now_utc(self) -> datetime:
        return self.current_utc

    def monotonic(self) -> float:
        return self.current_monotonic

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("FakeClock cannot move backwards")
        self.current_utc += timedelta(seconds=seconds)
        self.current_monotonic += seconds


@dataclass(frozen=True)
class NodeTiming:
    clock: Clock
    started_at: datetime
    started_monotonic: float


_NODE_TIMING: ContextVar[NodeTiming | None] = ContextVar("agent_node_timing", default=None)


def begin_node_timing(clock: Clock) -> Token[NodeTiming | None]:
    return _NODE_TIMING.set(NodeTiming(clock, clock.now_utc(), clock.monotonic()))


def end_node_timing(token: Token[NodeTiming | None]) -> None:
    _NODE_TIMING.reset(token)


def current_node_timing() -> NodeTiming | None:
    return _NODE_TIMING.get()
