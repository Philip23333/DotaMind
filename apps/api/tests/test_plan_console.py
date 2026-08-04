from fastapi.testclient import TestClient

from app.main import app


def test_plan_console_is_served_by_api() -> None:
    response = TestClient(app).get("/debug/plan")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "DotaMind Plan Lab" in response.text
    assert 'fetch("/api/v1/plan"' in response.text
    assert "Node Flow" in response.text
    assert "Validated Decision" in response.text
    assert "Required Evidence Sources" in response.text
    assert "Runtime / Attempt / Budget" in response.text
    assert 'setJson("runtime", sanitizeForDebug(payload.runtime))' in response.text
    assert "Terminal Stage" in response.text
    assert "Slowest Node" in response.text
    assert "Failure Stage" in response.text
    assert "renderAttemptSummary" in response.text
    assert "nodeDurations" in response.text
    assert "Budget limits / used" in response.text
    assert "shortId(call.tool_call_id)" in response.text
    assert "Controller Prompt Messages" not in response.text
    assert "Controller Raw Content" not in response.text
    assert "Final User Output" in response.text
    assert "Parsed Final Data" in response.text
    assert "Raw JSON" in response.text
    assert "response_type" in response.text
