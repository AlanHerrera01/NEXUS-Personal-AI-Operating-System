from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.application.security.audit import AuditEntry
from app.domain.entities.agent_action import AgentAction
from app.domain.entities.agent_run import AgentRun
from app.domain.entities.memory import Memory
from app.domain.entities.permission_request import PermissionRequest
from app.domain.value_objects.agent_action_status import AgentActionStatus
from app.domain.value_objects.agent_run_status import AgentRunStatus
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.memory_type import MemoryType
from app.domain.value_objects.permission_request_status import PermissionRequestStatus
from app.domain.value_objects.risk_level import RiskLevel
from app.main import app
from app.presentation.dependencies.activity import (
    get_activity_action_repository,
    get_activity_agent_run_repository,
    get_activity_memory_repository,
    get_activity_permission_request_repository,
)
from app.presentation.dependencies.identity import LOCAL_USER_ID
from app.presentation.dependencies.security import get_security_audit

USER = EntityId(LOCAL_USER_ID)
OTHER = EntityId.new()
NOW = datetime.now(timezone.utc)


class FakeRunRepository:
    def __init__(self, runs=None, fail: bool = False) -> None:
        self.runs = runs or []
        self.fail = fail

    def list_by_user(self, user_id, limit: int = 200):
        if self.fail:
            raise RuntimeError("database is down")
        return [run for run in self.runs if run.user_id == user_id][:limit]


class FakeActionRepository:
    def __init__(self, actions=None, fail: bool = False) -> None:
        self.actions = actions or []
        self.fail = fail

    def list_recent_for_user(self, user_id, limit: int = 200):
        if self.fail:
            raise RuntimeError("database is down")
        return self.actions[:limit]


class FakePermissionRequestRepository:
    def __init__(self, requests=None, fail: bool = False) -> None:
        self.requests = requests or []
        self.fail = fail

    def list_all(self):
        if self.fail:
            raise RuntimeError("database is down")
        return self.requests


class FakeMemoryRepository:
    def __init__(self, memories=None, fail: bool = False) -> None:
        self.memories = memories or []
        self.fail = fail

    def list_by_user(self, user_id, limit: int = 200):
        if self.fail:
            raise RuntimeError("database is down")
        return [memory for memory in self.memories if memory.user_id == user_id][:limit]


class FakeAuditLog:
    """Minimal stand-in for the in-memory ring: the route only reads and counts."""

    def __init__(self, entries=None) -> None:
        self._entries = tuple(entries or [])

    def entries(self):
        return self._entries

    def __len__(self) -> int:
        return len(self._entries)


def _override(runs=None, actions=None, requests=None, memories=None, audit=None, fail=False):
    app.dependency_overrides[get_activity_agent_run_repository] = lambda: FakeRunRepository(
        runs, fail
    )
    app.dependency_overrides[get_activity_action_repository] = lambda: FakeActionRepository(
        actions, fail
    )
    app.dependency_overrides[get_activity_permission_request_repository] = (
        lambda: FakePermissionRequestRepository(requests, fail)
    )
    app.dependency_overrides[get_activity_memory_repository] = lambda: FakeMemoryRepository(
        memories, fail
    )
    app.dependency_overrides[get_security_audit] = lambda: audit if audit is not None else FakeAuditLog()


def teardown_function() -> None:
    # Remove only the keys this module installs. ``clear()`` would wipe the
    # module-level overrides other test files register at import time.
    for dependency in (
        get_activity_agent_run_repository,
        get_activity_action_repository,
        get_activity_permission_request_repository,
        get_activity_memory_repository,
        get_security_audit,
    ):
        app.dependency_overrides.pop(dependency, None)


def _run(status=AgentRunStatus.COMPLETED, *, user=USER, created=None, updated=None):
    run = AgentRun(
        agent_id=EntityId.new(), user_request="Audit dependencies", user_id=user, status=status
    )
    run.created_at = created or NOW - timedelta(minutes=30)
    run.updated_at = updated or NOW - timedelta(minutes=5)
    return run


def test_activity_merges_the_owned_sources() -> None:
    run = _run()
    completed = AgentAction(
        agent_run_id=run.id,
        skill_name="fs",
        action_name="read_file",
        status=AgentActionStatus.COMPLETED,
        risk_level=RiskLevel.LOW,
        created_at=NOW - timedelta(minutes=20),
    )
    blocked = AgentAction(
        agent_run_id=run.id,
        skill_name="docker",
        action_name="prune_volumes",
        status=AgentActionStatus.BLOCKED,
        risk_level=RiskLevel.HIGH,
        created_at=NOW - timedelta(minutes=18),
    )
    pending = PermissionRequest(
        agent_run_id=run.id,
        tool_name="github.merge_pull_request",
        skill_name="github",
        reason="Merge without review",
        risk_level=RiskLevel.HIGH,
        user_id=USER,
        created_at=NOW - timedelta(minutes=10),
    )
    memory = Memory(
        content="Uses Docker locally for isolation",
        memory_type=MemoryType.SEMANTIC,
        user_id=USER,
        agent_id=EntityId.new(),
        created_at=NOW - timedelta(minutes=8),
    )
    # Another user's request must never surface on this feed.
    foreign = PermissionRequest(
        agent_run_id=run.id,
        tool_name="docker_host.prune",
        skill_name="docker",
        reason="Clean up",
        risk_level=RiskLevel.HIGH,
        user_id=OTHER,
    )
    audit = FakeAuditLog(
        [
            AuditEntry(
                event="TOOL_DENIED",
                user_id=str(USER),
                tool_name="fs.write_file",
                reason="Protected path",
                timestamp=NOW - timedelta(minutes=15),
            )
        ]
    )

    _override(
        runs=[run],
        actions=[completed, blocked],
        requests=[pending, foreign],
        memories=[memory],
        audit=audit,
    )

    response = TestClient(app).get("/api/v1/activity")

    assert response.status_code == 200
    body = response.json()
    kinds = {event["kind"] for event in body["events"]}
    assert {"ACTION_COMPLETED", "ACTION_BLOCKED", "PERMISSION_PENDING", "TOOL_DENIED", "RUN_STARTED"} <= kinds
    assert "MEMORY_SAVED" in kinds
    assert {"TOOL", "TRUST", "MEMORY", "RUN"} <= {event["category"] for event in body["events"]}
    # The foreign request is not represented anywhere.
    assert all(event["id"] != f"permission:{foreign.id}" for event in body["events"])
    # A denial is a first-class outcome with its cause attached.
    denied = [event for event in body["events"] if event["outcome"] == "DENIED"]
    assert denied and any(event["detail"] == "Protected path" for event in denied)
    # The pending approval is flagged resolvable so the UI can offer the buttons.
    pending_event = next(event for event in body["events"] if event["kind"] == "PERMISSION_PENDING")
    assert pending_event["payload"]["resolvable"] is True
    # Events are ordered newest first.
    stamps = [event["timestamp"] for event in body["events"]]
    assert stamps == sorted(stamps, reverse=True)


def test_activity_summary_counts_categories_and_success_rate() -> None:
    run = _run()
    _override(
        runs=[run],
        actions=[
            AgentAction(
                agent_run_id=run.id,
                skill_name="fs",
                action_name="read_file",
                status=AgentActionStatus.COMPLETED,
            ),
            AgentAction(
                agent_run_id=run.id,
                skill_name="docker",
                action_name="prune_volumes",
                status=AgentActionStatus.FAILED,
            ),
        ],
    )

    body = TestClient(app).get("/api/v1/activity").json()
    summary = body["summary"]
    counts = {entry["category"]: entry["count"] for entry in summary["categories"]}

    assert summary["total"] == len(body["events"])
    assert counts["TOOL"] == 2
    assert counts["RUN"] >= 1
    assert summary["resolved"] >= 3
    assert summary["success_rate"] is not None
    assert 0.0 <= summary["success_rate"] <= 1.0
    assert len(summary["density"]) == 24
    assert summary["density_peak"] >= 1


def test_activity_window_excludes_older_events() -> None:
    old = Memory(
        content="Old preference",
        memory_type=MemoryType.PREFERENCE,
        user_id=USER,
        created_at=NOW - timedelta(days=10),
    )
    recent = Memory(
        content="Recent preference",
        memory_type=MemoryType.PREFERENCE,
        user_id=USER,
        created_at=NOW - timedelta(hours=1),
    )
    _override(memories=[old, recent])

    last_day = TestClient(app).get("/api/v1/activity?window=24h").json()
    everything = TestClient(app).get("/api/v1/activity?window=all").json()

    day_ids = {event["id"] for event in last_day["events"]}
    all_ids = {event["id"] for event in everything["events"]}
    assert f"memory:{recent.id}" in day_ids
    assert f"memory:{old.id}" not in day_ids
    assert f"memory:{old.id}" in all_ids


def test_activity_reports_truncation() -> None:
    memories = [
        Memory(content=f"note {index}", memory_type=MemoryType.SEMANTIC, user_id=USER)
        for index in range(5)
    ]
    _override(memories=memories)

    body = TestClient(app).get("/api/v1/activity?limit=2").json()

    assert body["truncated"] is True
    assert len(body["events"]) == 2
    assert body["summary"]["total"] == 5


def test_activity_degrades_to_the_audit_trail_when_storage_is_down() -> None:
    audit = FakeAuditLog(
        [AuditEntry(event="RATE_LIMIT_EXCEEDED", tool_name="agent_runs", timestamp=NOW)]
    )
    _override(fail=True, audit=audit)

    body = TestClient(app).get("/api/v1/activity").json()

    assert body["storage_available"] is False
    assert [event["kind"] for event in body["events"]] == ["RATE_LIMIT_EXCEEDED"]
    assert body["summary"]["total"] == 1
    assert body["audit"]["persisted"] is False
    assert body["audit"]["retained_entries"] == 1


def test_activity_hides_another_users_audit_entries() -> None:
    audit = FakeAuditLog(
        [
            AuditEntry(event="TOOL_DENIED", user_id=str(USER), reason="mine", timestamp=NOW),
            AuditEntry(event="TOOL_DENIED", user_id=str(OTHER), reason="theirs", timestamp=NOW),
            AuditEntry(event="RATE_LIMIT_EXCEEDED", user_id=None, reason="process", timestamp=NOW),
        ]
    )
    _override(audit=audit)

    body = TestClient(app).get("/api/v1/activity").json()
    reasons = {event["detail"] for event in body["events"]}

    assert "mine" in reasons
    assert "process" in reasons
    assert "theirs" not in reasons
    assert body["audit"]["visible_entries"] == 2
    assert body["audit"]["retained_entries"] == 3
