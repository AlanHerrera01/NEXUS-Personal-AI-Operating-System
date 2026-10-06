import pytest

from app.domain.entities.agent import Agent
from app.domain.entities.agent_action import AgentAction
from app.domain.entities.agent_run import AgentRun
from app.domain.entities.execution_plan import ExecutionPlan
from app.domain.entities.memory import Memory
from app.domain.entities.permission import Permission
from app.domain.entities.plan_step import PlanStep
from app.domain.entities.skill import Skill
from app.domain.entities.task import Task
from app.domain.services.agent_run_state_service import AgentRunStateService
from app.domain.value_objects.agent_action_status import AgentActionStatus
from app.domain.value_objects.agent_run_status import AgentRunStatus
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.memory_persistence import MemoryPersistenceDecision
from app.domain.value_objects.memory_type import MemoryType
from app.domain.value_objects.permission_decision import PermissionDecision
from app.domain.value_objects.plan_step_status import PlanStepStatus
from app.domain.value_objects.risk_level import RiskLevel
from app.domain.value_objects.task_status import TaskStatus


def test_agent_requires_name_and_has_active_status() -> None:
    agent = Agent(name="NEXUS")

    assert agent.status.value == "ACTIVE"
    with pytest.raises(ValueError):
        Agent(name=" ")


def test_agent_run_transitions_are_controlled() -> None:
    run = AgentRun(agent_id=EntityId.new(), user_request="Prepare my day")
    service = AgentRunStateService()

    service.transition(run, AgentRunStatus.CONTEXT_LOADING)
    service.transition(run, AgentRunStatus.PLANNING)
    service.transition(run, AgentRunStatus.EXECUTING)
    service.transition(run, AgentRunStatus.OBSERVING)
    service.transition(run, AgentRunStatus.COMPLETED)

    assert run.status is AgentRunStatus.COMPLETED
    with pytest.raises(ValueError):
        service.transition(run, AgentRunStatus.EXECUTING)


def test_execution_plan_preserves_step_order() -> None:
    plan = ExecutionPlan(agent_run_id=EntityId.new())
    plan.add_step(PlanStep(1, "tasks", "list"))
    plan.add_step(PlanStep(2, "calendar", "read"))

    assert [step.order for step in plan.steps] == [1, 2]
    with pytest.raises(ValueError):
        plan.add_step(PlanStep(4, "tasks", "create"))


def test_plan_step_cannot_execute_when_blocked() -> None:
    step = PlanStep(1, "filesystem", "read_sensitive", risk_level=RiskLevel.HIGH)
    step.transition_to(PlanStepStatus.BLOCKED)

    with pytest.raises(ValueError):
        step.transition_to(PlanStepStatus.EXECUTING)


def test_memory_persistence_decision_is_deterministic() -> None:
    saved = Memory("Prefers concise updates", MemoryType.PREFERENCE)
    private = Memory(
        "Sensitive note",
        MemoryType.EPISODIC,
        MemoryPersistenceDecision.DO_NOT_SAVE,
    )

    assert saved.can_be_persisted
    assert not private.can_be_persisted


def test_task_transitions_and_required_fields() -> None:
    task = Task("Prepare demo")
    task.transition_to(TaskStatus.IN_PROGRESS)
    task.transition_to(TaskStatus.COMPLETED)

    assert task.status is TaskStatus.COMPLETED
    with pytest.raises(ValueError):
        Task("")
    with pytest.raises(ValueError):
        task.transition_to(TaskStatus.CANCELLED)


def test_skill_permission_and_action_model_security_metadata() -> None:
    skill = Skill("calendar", "Read and create calendar events", RiskLevel.MEDIUM)
    permission = Permission(
        user_id=EntityId.new(),
        agent_id=EntityId.new(),
        skill_name="calendar",
        action_name="create_event",
        scope="write",
        effect=PermissionDecision.ASK,
        risk_level=RiskLevel.MEDIUM,
    )
    action = AgentAction(EntityId.new(), "calendar", "create_event")

    action.transition_to(AgentActionStatus.APPROVED)
    assert skill.enabled
    assert permission.effect is PermissionDecision.ASK
    assert action.status is AgentActionStatus.APPROVED
