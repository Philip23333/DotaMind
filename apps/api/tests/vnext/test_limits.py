from app.vnext.agent.limits import AgentLimits


def test_agent_limits_default_answer_timeout() -> None:
    limits = AgentLimits()

    assert limits.answer_timeout_seconds == 40.0
    assert limits.degraded_answer_timeout_seconds == 15.0
    assert limits.deadline_seconds == 120.0
    assert limits.max_steps == 20
    assert limits.default_tool_timeout == 60.0
