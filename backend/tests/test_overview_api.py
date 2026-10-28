from fastapi.testclient import TestClient

from app.domain.entities.agent import Agent
from app.domain.entities.agent_run import AgentRun
from app.domain.entities.permission import Permission
from app.domain.entities.permission_request import PermissionRequest
from app.domain.value_objects.agent_run_status import AgentRunStatus
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_decision import PermissionDecision
from app.domain.value_objects.permission_request_status import PermissionRequestStatus
from app.domain.value_objects.risk_level import RiskLevel
from app.main import app
from app.presentation.dependencies.identity import LOCAL_USER_ID
from app.presentation.dependencies.overview import (
    get_overview_agent_repository,
    get_overview_agent_run_repository,
    get_overview_permission_repository,
    get_overview_permission_request_repository,
)

USER = EntityId(LOCAL_USER_ID)


class FakeRunRepository:
    def __init__(self, runs: list[AgentRun] | None = None, fail: bool = False) -> None:
        self.runs = runs or []
        self.fail = fail

    def list_by_user(self, user_id, limit: int = 50):
        if self.fail:
            raise RuntimeError("database is down")
        return [run for run in self.runs if run.user_id == user_id][:limit]


class FakeAgentRepository:
    def __init__(self, agents: list[Agent] | None = None, fail: bool = False) -> None:
        self.agents = agents or []
        self.fail = fail

    def list_by_user(self, user_id):
        if self.fail:
            raise RuntimeError("database is down")
        return [agent for agent in self.agents if agent.user_id == user_id]


class FakePermissionRepository:
    def __init__(self, permissions: list[Permission] | None = None, fail: bool = False) -> None:
        self.permissions = permissions or []
        self.fail = fail

    def list_all(self):
        if self.fail:
            raise RuntimeError("database is down")
        return self.permissions


class FakePermissionRequestRepository:
    def __init__(self, requests: list[PermissionRequest] | None = None, fail: bool = False) -> None:
        self.requests = requests or []
        self.fail = fail

    def list_all(self):
        if self.fail:
            raise RuntimeError("database is down")
        return self.requests


def _override(runs, agents, permissions, requests):
    app.dependency_overrides[get_overview_agent_run_repository] = lambda: runs
    app.dependency_overrides[get_overview_agent_repository] = lambda: agents
    app.dependency_overrides[get_overview_permission_repository] = lambda: permissions
    app.dependency_overrides[get_overview_permission_request_repository] = lambda: requests


def teardown_function() -> None:
    # Remove only the keys this module installs. ``clear()`` would wipe the
    # module-level overrides other test files register at import time.
    for dependency in (
        get_overview_agent_run_repository,
        get_overview_agent_repository,
        get_overview_permission_repository,
        get_overview_permission_request_repository,
    ):
        app.dependency_overrides.pop(dependency, None)


def test_overview_summarises_owned_state() -> None:
    agent_id = EntityId.new()
    active_run = AgentRun(
        agent_id=agent_id,
        user_request="Audit dependencies and summarise CVEs",
        user_id=USER,
        status=AgentRunStatus.EXECUTING,
    )
    finished_run = AgentRun(
        agent_id=agent_id,
        user_request="Clean temporary logs",
        user_id=USER,
        status=AgentRunStatus.COMPLETED,
    )
    allowed = Permission(
        user_id=USER,
        agent_id=agent_id,
        skill_name="tasks",
        action_name="list",
        scope="user",
        effect=PermissionDecision.ALLOW,
        risk_level=RiskLevel.LOW,
    )
    denied = Permission(
        user_id=USER,
        agent_id=agent_id,
        skill_name="docker",
        action_name="prune_volumes",
        scope="user",
        effect=PermissionDecision.DENY,
        risk_level=RiskLevel.HIGH,
    )
    pending = PermissionRequest(
        agent_run_id=active_run.id,
        tool_name="github_cli.merge_pull_request",
        skill_name="github",
        reason="Merge a branch without prior review",
        risk_level=RiskLevel.HIGH,
        user_id=USER,
    )
    # A request that another user owns must never appear on this dashboard.
    other_pending = PermissionRequest(
        agent_run_id=active_run.id,
        tool_name="docker_host.prune_volumes",
        skill_name="docker",
        reason="Clean up",
        risk_level=RiskLevel.HIGH,
        user_id=EntityId.new(),
    )

    _override(
        FakeRunRepository([active_run, finished_run]),
        FakeAgentRepository([Agent(id=agent_id, name="Personal Operator", user_id=USER)]),
        FakePermissionRepository([allowed, denied]),
        FakePermissionRequestRepository([pending, other_pending]),
    )

    response = TestClient(app).get("/api/v1/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["runs"]["active_count"] == 1
    assert body["runs"]["items"][0]["run_id"] == str(active_run.id)
    assert body["runs"]["items"][0]["status"] == "EXECUTING"
    # The recent list is every run the owner has, in-flight or not: a finished
    # run must still be reachable so its thread can be reopened.
    assert {item["run_id"] for item in body["runs"]["recent"]} == {
        str(active_run.id),
        str(finished_run.id),
    }
    assert body["trust"]["allow_grants"] == 1
    assert body["trust"]["deny_grants"] == 1
    assert body["trust"]["total_grants"] == 2
    assert body["authorizations"]["pending_count"] == 1
    assert body["authorizations"]["items"][0]["request_id"] == str(pending.id)
    assert body["authorizations"]["items"][0]["risk_level"] == "HIGH"
    assert body["agent"] == {"id": str(agent_id), "name": "Personal Operator"}
    assert body["model"]["provider"] == "nebius"


def test_overview_degrades_when_storage_is_unavailable() -> None:
    _override(
        FakeRunRepository(fail=True),
        FakeAgentRepository(fail=True),
        FakePermissionRepository(fail=True),
        FakePermissionRequestRepository(fail=True),
    )

    response = TestClient(app).get("/api/v1/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["runs"] == {"active_count": 0, "items": [], "recent": []}
    assert body["authorizations"] == {"pending_count": 0, "items": []}
    assert body["trust"]["total_grants"] == 0
    assert body["agent"] is None
    # Health and model state are still served so the page renders.
    assert body["system"]["database"] in {"up", "down"}
    assert body["model"]["model"]
