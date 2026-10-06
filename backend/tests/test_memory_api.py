from fastapi.testclient import TestClient

from app.application.memory.firewall import MemoryFirewall
from app.application.memory.policy import DeterministicMemoryPolicy
from app.application.memory.service import MemoryService
from app.main import app
from app.presentation.dependencies.memory import memory_service_dependency
from tests.unit.application.test_memory_system import FakeMemoryRepository


repository = FakeMemoryRepository()
service = MemoryService(repository, DeterministicMemoryPolicy(), MemoryFirewall())
app.dependency_overrides[memory_service_dependency] = lambda: service
client = TestClient(app)


def test_memory_api_applies_policy_and_returns_dto() -> None:
    response = client.post(
        "/api/v1/memories",
        json={
            "agent_id": "00000000-0000-0000-0000-000000000001",
            "content": "The user prefers Docker for development.",
            "memory_type": "PREFERENCE",
            "source": "USER_EXPLICIT",
            "importance": "HIGH",
        },
    )

    assert response.status_code == 200
    assert response.json()["saved"] is True
    assert response.json()["memory"]["content"] == "The user prefers Docker for development."


def test_memory_api_does_not_persist_opt_out() -> None:
    response = client.post(
        "/api/v1/memories",
        json={
            "agent_id": "00000000-0000-0000-0000-000000000002",
            "content": "No guardes esta información privada.",
            "memory_type": "EPISODIC",
            "source": "CONVERSATION",
            "importance": "MEDIUM",
            "user_instruction": "No guardes esto.",
        },
    )

    assert response.status_code == 200
    assert response.json()["saved"] is False
    assert response.json()["memory"] is None
