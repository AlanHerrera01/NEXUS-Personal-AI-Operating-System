from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_versioned_health_check() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "nexus-backend"
    assert response.json()["phase"] == "4"
    assert response.json()["database"] in {"up", "down"}


def test_legacy_unimplemented_routes_are_not_exposed() -> None:
    assert client.get("/api/v1/memory").status_code == 404
    assert client.get("/api/v1/tasks").status_code == 404
