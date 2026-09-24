from app.vnext.agent.limits import AgentLimits


def test_agent_limits_default_answer_timeout() -> None:
    limits = AgentLimits()

    assert limits.answer_timeout_seconds == 60.0
    assert limits.deadline_seconds == 300.0
    assert limits.default_tool_timeout == 60.0
