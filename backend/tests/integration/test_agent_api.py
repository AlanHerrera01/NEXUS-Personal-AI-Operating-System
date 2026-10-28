import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.domain.entities.agent import Agent
from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.persistence.database import SessionFactory
from app.infrastructure.persistence.models import AgentModel, TaskModel
from app.infrastructure.persistence.repositories.agent_repository import SqlAlchemyAgentRepository
from app.main import app
from app.presentation.dependencies.identity import LOCAL_USER_ID

pytestmark = pytest.mark.integration


def test_agent_run_executes_task_tool_and_completes(monkeypatch) -> None:
    # This verifies API -> policy -> tool -> database, without spending provider
    # credits or depending on a developer's real LLM credentials.
    from app.application.agents.rule_based_brain import RuleBasedAgentBrain
    from app.presentation.dependencies import agent as agent_dependencies

    monkeypatch.setattr(agent_dependencies, "build_agent_brain", lambda _settings: RuleBasedAgentBrain())
    session = SessionFactory()
    agent = SqlAlchemyAgentRepository(session).save(
        Agent(name="Orchestrator integration", user_id=EntityId(LOCAL_USER_ID))
    )
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
