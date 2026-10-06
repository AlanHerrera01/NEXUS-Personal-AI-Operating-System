import asyncio
from datetime import UTC, datetime

import pytest

from app.domain.ports.tool import ToolContext
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.risk_level import RiskLevel
from app.domain.value_objects.task_status import TaskStatus
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.skills.tasks.skill import TaskSkill
from app.infrastructure.skills.tasks.tools.complete_task import TaskCompleteTool
from app.infrastructure.skills.tasks.tools.create_task import TaskCreateTool
from app.infrastructure.skills.tasks.tools.get_task import TaskGetTool
from app.infrastructure.skills.tasks.tools.list_tasks import TaskListTool
from app.infrastructure.skills.tasks.tools.update_task import TaskUpdateTool
from tests.support.repositories import FakeTaskRepository, FailingTaskRepository, make_task


@pytest.fixture
def repository() -> FakeTaskRepository:
    return FakeTaskRepository()


@pytest.fixture
def context() -> ToolContext:
    return ToolContext(agent_id=EntityId.new(), agent_run_id=EntityId.new())


def run(coroutine):
    return asyncio.run(coroutine)


def test_skill_exposes_five_namespaced_tools(repository: FakeTaskRepository) -> None:
    skill = TaskSkill(repository)

    definition = skill.definition()

    assert definition.name == "tasks"
    assert definition.enabled is True
    assert [tool.definition().name for tool in skill.tools()] == [
        "task.create",
        "task.list",
        "task.get",
        "task.update",
        "task.complete",
    ]
    assert all(tool.definition().skill_name == "tasks" for tool in skill.tools())


def test_tool_metadata_declares_risk_and_side_effects(repository: FakeTaskRepository) -> None:
    tools = {tool.definition().name: tool.definition() for tool in TaskSkill(repository).tools()}

    assert tools["task.list"].read_only is True
    assert tools["task.list"].side_effect is False
    assert tools["task.get"].read_only is True
    assert tools["task.create"].read_only is False
    assert tools["task.create"].side_effect is True
    assert tools["task.update"].side_effect is True
    assert tools["task.complete"].side_effect is True
    assert tools["task.create"].risk_level is RiskLevel.LOW
    assert all(definition.input_schema["additionalProperties"] is False for definition in tools.values())


def test_task_create_persists_through_the_use_case(repository: FakeTaskRepository, context: ToolContext) -> None:
    result = run(TaskCreateTool(repository).execute({"title": "Review NEXUS docs", "description": "phase 7"}, context))

    assert result.success is True
    assert result.tool_name == "task.create"
    assert result.data["title"] == "Review NEXUS docs"
    assert result.data["status"] == TaskStatus.PENDING.value
    assert len(repository.items) == 1
    assert result.metadata["skill"] == "tasks"


def test_task_create_accepts_iso_due_date(repository: FakeTaskRepository, context: ToolContext) -> None:
    result = run(TaskCreateTool(repository).execute({"title": "Ship it", "due_date": "2030-01-02T03:04:05Z"}, context))

    assert result.success is True
    assert result.data["due_date"].startswith("2030-01-02T03:04:05")


def test_task_create_rejects_missing_title(repository: FakeTaskRepository, context: ToolContext) -> None:
    result = run(TaskCreateTool(repository).execute({"description": "no title"}, context))

    assert result.success is False
    assert result.error_code == ToolErrorCode.INVALID_ARGUMENTS
    assert "title" in result.error_message
    assert repository.items == {}


def test_task_create_rejects_unknown_arguments(repository: FakeTaskRepository, context: ToolContext) -> None:
    result = run(TaskCreateTool(repository).execute({"title": "x", "owner": "root"}, context))

    assert result.success is False
    assert result.error_code == ToolErrorCode.INVALID_ARGUMENTS


def test_task_create_rejects_identity_arguments_from_the_model(
    repository: FakeTaskRepository, context: ToolContext
) -> None:
    result = run(TaskCreateTool(repository).execute({"title": "x", "agent_id": str(EntityId.new())}, context))

    assert result.success is False
    assert result.error_code == ToolErrorCode.FORBIDDEN_ARGUMENTS
    assert repository.items == {}


def test_task_create_reports_repository_failures_without_leaking_internals(context: ToolContext) -> None:
    result = run(TaskCreateTool(FailingTaskRepository()).execute({"title": "x"}, context))

    assert result.success is False
    assert result.error_code == ToolErrorCode.TOOL_EXECUTION_FAILED
    assert "Traceback" not in result.error_message
    assert "connection reset" not in result.error_message


def test_task_list_only_returns_tasks_of_the_context_agent(repository: FakeTaskRepository, context: ToolContext) -> None:
    other_agent = EntityId.new()
    repository.save(make_task(context.agent_id, "Mine"))
    repository.save(make_task(other_agent, "Not mine"))

    result = run(TaskListTool(repository).execute({}, context))

    assert result.success is True
    assert result.data["count"] == 1
    assert result.data["items"][0]["title"] == "Mine"


def test_task_list_filters_by_status(repository: FakeTaskRepository, context: ToolContext) -> None:
    pending = repository.save(make_task(context.agent_id, "Pending"))
    completed = repository.save(make_task(context.agent_id, "Completed"))
    completed.transition_to(TaskStatus.COMPLETED)

    result = run(TaskListTool(repository).execute({"status": "COMPLETED"}, context))

    assert [item["task_id"] for item in result.data["items"]] == [str(completed.id)]
    assert pending.title == "Pending"


def test_task_list_rejects_invalid_status(repository: FakeTaskRepository, context: ToolContext) -> None:
    result = run(TaskListTool(repository).execute({"status": "DONE"}, context))

    assert result.success is False
    assert result.error_code == ToolErrorCode.INVALID_ARGUMENTS


def test_task_get_returns_the_task(repository: FakeTaskRepository, context: ToolContext) -> None:
    task = repository.save(make_task(context.agent_id, "Review"))

    result = run(TaskGetTool(repository).execute({"task_id": str(task.id)}, context))

    assert result.success is True
    assert result.data["task_id"] == str(task.id)


def test_task_get_reports_missing_task(context: ToolContext) -> None:
    result = run(TaskGetTool(FakeTaskRepository()).execute({"task_id": str(EntityId.new())}, context))

    assert result.success is False
    assert result.error_code == ToolErrorCode.TASK_NOT_FOUND


def test_task_get_cannot_read_another_users_task(repository: FakeTaskRepository, context: ToolContext) -> None:
    task = repository.save(make_task(EntityId.new(), "Private"))

    result = run(TaskGetTool(repository).execute({"task_id": str(task.id)}, context))

    assert result.success is False
    assert result.error_code == ToolErrorCode.TASK_NOT_FOUND


def test_task_get_rejects_malformed_identifier(repository: FakeTaskRepository, context: ToolContext) -> None:
    result = run(TaskGetTool(repository).execute({"task_id": "../../etc/passwd"}, context))

    assert result.success is False
    assert result.error_code == ToolErrorCode.INVALID_ARGUMENTS


def test_task_update_changes_only_provided_fields(repository: FakeTaskRepository, context: ToolContext) -> None:
    task = repository.save(make_task(context.agent_id, "Old", description="keep me"))

    result = run(TaskUpdateTool(repository).execute({"task_id": str(task.id), "title": "New"}, context))

    assert result.success is True
    assert result.data["title"] == "New"
    assert result.data["description"] == "keep me"


def test_task_update_accepts_due_date_and_status(repository: FakeTaskRepository, context: ToolContext) -> None:
    task = repository.save(make_task(context.agent_id, "Old"))

    result = run(
        TaskUpdateTool(repository).execute(
            {"task_id": str(task.id), "due_date": "2031-05-06T00:00:00Z", "status": "IN_PROGRESS"},
            context,
        )
    )

    assert result.success is True
    assert result.data["status"] == TaskStatus.IN_PROGRESS.value
    assert result.data["due_date"].startswith("2031-05-06")


def test_task_update_rejects_invalid_transition(repository: FakeTaskRepository, context: ToolContext) -> None:
    task = repository.save(make_task(context.agent_id, "Done"))
    task.transition_to(TaskStatus.COMPLETED)
    repository.save(task)

    result = run(
        TaskUpdateTool(repository).execute({"task_id": str(task.id), "status": "IN_PROGRESS"}, context)
    )

    assert result.success is False
    assert result.error_code == ToolErrorCode.TASK_TRANSITION_INVALID


def test_task_update_reports_missing_task(context: ToolContext) -> None:
    result = run(TaskUpdateTool(FakeTaskRepository()).execute({"task_id": str(EntityId.new())}, context))

    assert result.success is False
    assert result.error_code == ToolErrorCode.TASK_NOT_FOUND


def test_task_complete_marks_the_task_completed(repository: FakeTaskRepository, context: ToolContext) -> None:
    task = repository.save(make_task(context.agent_id, "Finish me"))

    result = run(TaskCompleteTool(repository).execute({"task_id": str(task.id)}, context))

    assert result.success is True
    assert result.data["status"] == TaskStatus.COMPLETED.value
    assert repository.items[task.id].status is TaskStatus.COMPLETED


def test_task_complete_is_idempotent(repository: FakeTaskRepository, context: ToolContext) -> None:
    task = repository.save(make_task(context.agent_id, "Finish me"))
    tool = TaskCompleteTool(repository)
    run(tool.execute({"task_id": str(task.id)}, context))

    result = run(tool.execute({"task_id": str(task.id)}, context))

    assert result.success is True


def test_task_complete_cannot_complete_another_users_task(repository: FakeTaskRepository, context: ToolContext) -> None:
    task = repository.save(make_task(EntityId.new(), "Private"))

    result = run(TaskCompleteTool(repository).execute({"task_id": str(task.id)}, context))

    assert result.success is False
    assert result.error_code == ToolErrorCode.TASK_NOT_FOUND
    assert task.status is TaskStatus.PENDING


def test_tools_never_call_the_llm_or_the_orchestrator() -> None:
    import inspect

    for module in (
        "app.infrastructure.skills.tasks.tools.create_task",
        "app.infrastructure.skills.tasks.tools.list_tasks",
        "app.infrastructure.skills.tasks.tools.get_task",
        "app.infrastructure.skills.tasks.tools.update_task",
        "app.infrastructure.skills.tasks.tools.complete_task",
    ):
        source = inspect.getsource(__import__(module, fromlist=["*"]))
        assert "llm" not in source.lower()
        assert "orchestrator" not in source.lower()
        assert "subprocess" not in source.lower()
        assert "eval(" not in source
        assert "exec(" not in source


def test_due_date_defaults_to_none(repository: FakeTaskRepository) -> None:
    task = make_task(EntityId.new(), "No deadline")

    assert task.due_date is None
    assert task.created_at <= datetime.now(UTC)
