import pytest
from fastapi.testclient import TestClient

from app.domain.entities.agent import Agent
from app.infrastructure.persistence.database import SessionFactory
from app.infrastructure.persistence.models import AgentModel
from app.infrastructure.persistence.repositories.agent_repository import SqlAlchemyAgentRepository
from app.main import app

pytestmark = pytest.mark.integration


def test_memory_api_round_trip_against_postgres() -> None:
    session = SessionFactory()
    agent = SqlAlchemyAgentRepository(session).save(Agent(name="Memory API integration"))
    session.close()
    client = TestClient(app)

    try:
        create = client.post(
            "/api/v1/memories",
            json={
                "agent_id": str(agent.id),
                "content": "The user prefers Docker for development.",
                "memory_type": "PREFERENCE",
                "source": "USER_EXPLICIT",
                "importance": "HIGH",
            },
        )
        assert create.status_code == 200
        memory_id = create.json()["memory"]["id"]

        listed = client.get(f"/api/v1/memories?agent_id={agent.id}")
        assert listed.status_code == 200
        assert len(listed.json()["items"]) == 1

        searched = client.post(
            "/api/v1/memories/search",
            json={"agent_id": str(agent.id), "query": "Docker", "limit": 5},
        )
        assert searched.status_code == 200
        assert len(searched.json()["items"]) == 1

        deleted = client.delete(f"/api/v1/memories/{memory_id}?agent_id={agent.id}")
        assert deleted.status_code == 204
    finally:
        cleanup = SessionFactory()
        model = cleanup.get(AgentModel, agent.id.value)
        if model is not None:
            cleanup.delete(model)
            cleanup.commit()
        cleanup.close()
