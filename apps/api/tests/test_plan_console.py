from fastapi.testclient import TestClient

from app.main import app


def test_plan_console_is_served_by_api() -> None:
    response = TestClient(app).get("/debug/plan")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "MetaMind Plan Lab" in response.text
    assert 'fetch("/api/v1/plan"' in response.text
    assert "Node Flow" in response.text
    assert "response_type" in response.text
