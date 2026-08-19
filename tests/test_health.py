from fastapi.testclient import TestClient

from tower.main import create_app


def test_health_returns_ok_status_with_service_metadata():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "glasses-tower"
    assert "version" in body
