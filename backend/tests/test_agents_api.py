"""The agent registry over HTTP.

The value under test is not "does it store a row" but the two properties that
make the route safe to expose: the caller never decides who owns an agent, and
activation leaves exactly one agent active so "the active agent" means one
thing. The dashboard, the objective bar and the runs page all read that.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.domain.entities.agent import Agent
from app.domain.value_objects.agent_status import AgentStatus
from app.domain.value_objects.entity_id import EntityId
from app.main import app
from app.presentation.dependencies.agents import get_agent_repository
from app.presentation.dependencies.identity import LOCAL_USER_ID

USER = EntityId(LOCAL_USER_ID)


class FakeAgentRepository:
    """In-memory stand-in for the ``agents`` table."""

    def __init__(self) -> None:
        self.items: dict[str, Agent] = {}

    def save(self, agent: Agent) -> Agent:
        self.items[str(agent.id)] = agent
        return agent

    def get_by_id(self, agent_id: EntityId, user_id: EntityId) -> Agent | None:
        agent = self.items.get(str(agent_id))
        if agent is None or agent.user_id != user_id:
            return None
        return agent

    def list_by_user(self, user_id: EntityId) -> list[Agent]:
        owned = [agent for agent in self.items.values() if agent.user_id == user_id]
        return sorted(owned, key=lambda agent: agent.created_at)


def _override(repository: FakeAgentRepository) -> None:
    app.dependency_overrides[get_agent_repository] = lambda: repository


def teardown_function() -> None:
    # Remove only the key this module installs; ``clear()`` would wipe the
    # module-level overrides other test files register at import time.
    app.dependency_overrides.pop(get_agent_repository, None)


def _own(
    repository: FakeAgentRepository, name: str, status: AgentStatus = AgentStatus.ACTIVE
) -> Agent:
    """An agent owned by the local user, as the API would have stored it."""
    agent = Agent(
        name=name, description=f"{name} description", user_id=USER, status=status
    )
    repository.save(agent)
    return agent


def test_list_is_empty_for_a_fresh_deployment() -> None:
    _override(FakeAgentRepository())

    body = TestClient(app).get("/api/v1/agents").json()

    assert body["items"] == []
    # Nothing to run against -- which is what the objective bar reports.
    assert body["active_id"] is None


def test_create_stores_an_agent_owned_by_the_caller_and_active() -> None:
    repository = FakeAgentRepository()
    _override(repository)
    client = TestClient(app)

    response = client.post(
        "/api/v1/agents",
        json={
            "name": "NEXUS",
            "description": "Personal AI",
            # Neither of these is readable from a create request.
            "user_id": "someone-else",
            "status": "INACTIVE",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "NEXUS"
    assert body["description"] == "Personal AI"
    # The entity's default, not whatever the payload asked for.
    assert body["status"] == "ACTIVE"
    assert repository.items[body["id"]].user_id == USER
    # Creating the first agent is what ends the "no active agent" dead end.
    assert client.get("/api/v1/agents").json()["active_id"] == body["id"]


def test_create_requires_a_name() -> None:
    _override(FakeAgentRepository())
    client = TestClient(app)

    assert client.post("/api/v1/agents", json={"name": ""}).status_code == 422
    assert client.post("/api/v1/agents", json={}).status_code == 422


def test_list_only_returns_the_callers_own_agents() -> None:
    repository = FakeAgentRepository()
    _override(repository)
    mine = _own(repository, "mine")
    repository.save(Agent(name="someone-elses", user_id=EntityId.new()))

    body = TestClient(app).get("/api/v1/agents").json()

    assert [item["name"] for item in body["items"]] == ["mine"]
    assert body["active_id"] == str(mine.id)


def test_activation_is_exclusive() -> None:
    repository = FakeAgentRepository()
    _override(repository)
    first = _own(repository, "first")
    second = _own(repository, "second")
    client = TestClient(app)

    response = client.patch(f"/api/v1/agents/{second.id}", json={"status": "ACTIVE"})

    assert response.status_code == 200
    assert response.json()["status"] == "ACTIVE"
    # The other agent is stood down in the same pass, so "the active agent" is
    # exactly one and does not depend on creation order.
    assert repository.items[str(first.id)].status is AgentStatus.INACTIVE
    assert client.get("/api/v1/agents").json()["active_id"] == str(second.id)


def test_deactivating_the_active_agent_leaves_none_active() -> None:
    repository = FakeAgentRepository()
    _override(repository)
    agent = _own(repository, "only")
    client = TestClient(app)

    response = client.patch(f"/api/v1/agents/{agent.id}", json={"status": "INACTIVE"})

    assert response.status_code == 200
    assert response.json()["status"] == "INACTIVE"
    # Reported honestly: the objective bar has nothing to run against again.
    assert client.get("/api/v1/agents").json()["active_id"] is None


def test_patch_is_owner_scoped_and_404s_for_an_unknown_id() -> None:
    repository = FakeAgentRepository()
    _override(repository)
    foreign = repository.save(Agent(name="foreign", user_id=EntityId.new()))
    client = TestClient(app)

    assert (
        client.patch(f"/api/v1/agents/{foreign.id}", json={"status": "ACTIVE"}).status_code
        == 404
    )
    assert (
        client.patch(f"/api/v1/agents/{foreign.id}", json={"name": "renamed"}).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/agents/{EntityId.new().value}", json={"status": "ACTIVE"}
        ).status_code
        == 404
    )
    # Untouched: a foreign agent is neither renamed nor activated.
    assert foreign.name == "foreign"
    assert foreign.status is AgentStatus.ACTIVE  # the fake stored it as-is


def test_patch_renames_without_touching_the_owner() -> None:
    repository = FakeAgentRepository()
    _override(repository)
    agent = _own(repository, "before")

    body = (
        TestClient(app)
        .patch(
            f"/api/v1/agents/{agent.id}",
            json={"name": "after", "description": "renamed"},
        )
        .json()
    )

    assert body["name"] == "after"
    assert body["description"] == "renamed"
    # Renaming an agent you own still may not hand it to someone else.
    assert repository.items[str(agent.id)].user_id == USER


def test_patch_rejects_a_status_outside_the_enum() -> None:
    repository = FakeAgentRepository()
    _override(repository)
    agent = _own(repository, "agent")

    response = TestClient(app).patch(
        f"/api/v1/agents/{agent.id}", json={"status": "PAUSED"}
    )

    assert response.status_code == 422
