from app.domain.entities.agent import Agent
from app.domain.entities.agent_run import AgentRun
from app.domain.entities.execution_plan import ExecutionPlan
from app.domain.entities.memory import Memory
from app.domain.entities.skill import Skill
from app.domain.entities.task import Task
from app.infrastructure.persistence.models import (
    AgentModel,
    AgentRunModel,
    ExecutionPlanModel,
    MemoryModel,
    SkillModel,
    TaskModel,
)
from app.domain.value_objects.agent_run_status import AgentRunStatus
from app.domain.value_objects.agent_status import AgentStatus
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.memory_persistence import MemoryPersistenceDecision
from app.domain.value_objects.memory_importance import MemoryImportance
from app.domain.value_objects.memory_source import MemorySource
from app.domain.value_objects.memory_type import MemoryType
from app.domain.value_objects.plan_status import PlanStatus
from app.domain.value_objects.risk_level import RiskLevel
from app.domain.value_objects.task_status import TaskStatus


def agent_to_model(agent: Agent) -> AgentModel:
    return AgentModel(
        id=agent.id.value,
        user_id=agent.user_id.value if agent.user_id else None,
        name=agent.name,
        description=agent.description,
        status=agent.status.value,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def agent_from_model(model: AgentModel) -> Agent:
    return Agent(
        id=EntityId(model.id),
        user_id=EntityId(model.user_id) if model.user_id else None,
        name=model.name,
        description=model.description,
        status=AgentStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def agent_run_to_model(agent_run: AgentRun) -> AgentRunModel:
    return AgentRunModel(
        id=agent_run.id.value,
        agent_id=agent_run.agent_id.value,
        user_id=agent_run.user_id.value if agent_run.user_id else None,
        user_request=agent_run.user_request,
        status=agent_run.status.value,
        created_at=agent_run.created_at,
        updated_at=agent_run.updated_at,
    )


def agent_run_from_model(model: AgentRunModel) -> AgentRun:
    return AgentRun(
        id=EntityId(model.id),
        agent_id=EntityId(model.agent_id),
        user_id=EntityId(model.user_id) if model.user_id else None,
        user_request=model.user_request,
        status=AgentRunStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def execution_plan_to_model(plan: ExecutionPlan) -> ExecutionPlanModel:
    return ExecutionPlanModel(
        id=plan.id.value,
        agent_run_id=plan.agent_run_id.value,
        status=plan.status.value,
        created_at=plan.created_at,
    )


def execution_plan_from_model(model: ExecutionPlanModel) -> ExecutionPlan:
    return ExecutionPlan(
        id=EntityId(model.id),
        agent_run_id=EntityId(model.agent_run_id),
        status=PlanStatus(model.status),
        created_at=model.created_at,
    )


def memory_to_model(memory: Memory) -> MemoryModel:
    if memory.agent_id is None:
        raise ValueError("memory requires an agent_id")
    return MemoryModel(
        id=memory.id.value,
        agent_id=memory.agent_id.value,
        # Nullable in the schema for legacy rows, but the firewall rejects an
        # unowned memory before this mapper is reached, so a model is only ever
        # built with an owner.
        user_id=memory.user_id.value if memory.user_id else None,
        content=memory.content,
        memory_type=memory.memory_type.value,
        persistence=memory.persistence.value,
        source=memory.source.value,
        importance=memory.importance.value,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )


def memory_from_model(model: MemoryModel) -> Memory:
    return Memory(
        id=EntityId(model.id),
        agent_id=EntityId(model.agent_id),
        user_id=EntityId(model.user_id) if model.user_id else None,
        content=model.content,
        memory_type=MemoryType(model.memory_type),
        persistence=MemoryPersistenceDecision(model.persistence),
        source=MemorySource(model.source),
        importance=MemoryImportance(model.importance),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def task_to_model(task: Task) -> TaskModel:
    return TaskModel(
        id=task.id.value,
        agent_id=task.agent_id.value if task.agent_id else None,
        title=task.title,
        description=task.description,
        status=task.status.value,
        due_date=task.due_date,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def task_from_model(model: TaskModel) -> Task:
    return Task(
        id=EntityId(model.id),
        agent_id=EntityId(model.agent_id) if model.agent_id else None,
        title=model.title,
        description=model.description,
        status=TaskStatus(model.status),
        due_date=model.due_date,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def skill_to_model(skill: Skill) -> SkillModel:
    return SkillModel(
        name=skill.name,
        description=skill.description,
        risk_level=skill.risk_level.value,
        enabled=skill.enabled,
    )


def skill_from_model(model: SkillModel) -> Skill:
    return Skill(
        name=model.name,
        description=model.description,
        risk_level=RiskLevel(model.risk_level),
        enabled=model.enabled,
    )
