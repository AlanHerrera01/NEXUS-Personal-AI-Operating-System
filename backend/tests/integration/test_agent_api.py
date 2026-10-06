import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.domain.entities.agent import Agent
from app.infrastructure.persistence.database import SessionFactory
from app.infrastructure.persistence.models import AgentModel, TaskModel
from app.infrastructure.persistence.repositories.agent_repository import SqlAlchemyAgentRepository
from app.main import app

pytestmark = pytest.mark.integration


def test_agent_run_executes_task_tool_and_completes() -> None:
    session = SessionFactory()
    agent = SqlAlchemyAgentRepository(session).save(Agent(name="Orchestrator integration"))
    session.close()
    client = TestClient(app)

    try:
        response = client.post(
            f"/api/v1/agents/{agent.id}/runs",
            json={"input": "Crea una tarea para revisar NEXUS"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "COMPLETED"
        assert body["response"]
        assert body["actions"][0]["tool_name"] == "task.create"
    finally:
        cleanup = SessionFactory()
        cleanup.execute(delete(TaskModel).where(TaskModel.agent_id == agent.id.value))
        model = cleanup.get(AgentModel, agent.id.value)
        if model is not None:
            cleanup.delete(model)
        cleanup.commit()
        cleanup.close()
