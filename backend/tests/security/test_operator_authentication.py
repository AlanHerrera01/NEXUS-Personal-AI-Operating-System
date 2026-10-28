import hashlib

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app
from app.presentation.dependencies import identity

KEY = "test-only-high-entropy-access-key-never-use-in-production"


@pytest.fixture
def client(monkeypatch):
    settings = Settings(_env_file=None, auth_token_hash=hashlib.sha256(KEY.encode()).hexdigest())
    monkeypatch.setattr(identity, "get_settings", lambda: settings)
    return TestClient(create_app())


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v1/overview"),
    ("GET", "/api/v1/settings"),
    ("GET", "/api/v1/conversations"),
    ("GET", "/api/v1/mcp-servers"),
    ("POST", "/api/v1/agent-runs/00000000-0000-0000-0000-000000000001/permission-requests/00000000-0000-0000-0000-000000000002/approve"),
    ("POST", "/api/v1/agents/00000000-0000-0000-0000-000000000001/runs"),
])
def test_api_rejects_unauthenticated_requests_before_storage_or_execution(client, method, path):
    response = client.request(method, path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("authorization", ["", "Bearer wrong", f"Basic {KEY}", f"Bearer {KEY} "])
def test_invalid_tokens_cannot_claim_the_operator(client, authorization):
    response = client.get("/api/v1/auth/me", headers={"Authorization": authorization, "X-User-ID": "attacker"})
    assert response.status_code == 401
    assert KEY not in response.text


def test_valid_key_preserves_existing_ownership_and_ignores_forged_identity(client):
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {KEY}", "X-User-ID": "attacker"})
    assert response.status_code == 200
    assert response.json() == {"user_id": str(identity.LOCAL_USER_ID)}


def test_unconfigured_authentication_fails_closed(monkeypatch):
    monkeypatch.setattr(identity, "get_settings", lambda: Settings(_env_file=None))
    response = TestClient(create_app()).get("/api/v1/auth/me", headers={"Authorization": f"Bearer {KEY}"})
    assert response.status_code == 503


def test_webhook_still_requires_its_own_secret(client):
    response = client.post("/api/v1/events/trigger", headers={"Authorization": f"Bearer {KEY}"}, json={"event_type": "test", "idempotency_key": "one", "payload": {}})
    assert response.status_code in {401, 503}
