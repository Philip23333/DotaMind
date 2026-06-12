from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentTask:
    agent: str
    action: str
    input: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentResult:
    agent: str
    output: dict[str, object]
    confidence: float = 0.0
