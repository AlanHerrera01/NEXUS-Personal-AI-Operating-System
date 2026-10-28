from __future__ import annotations

from app.domain.ports.tool import ToolContext
from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.skills.reminders.skill import ReminderSkill
from tests.support.repositories import FakeReminderRepository


def _tools(repository) -> dict[str, object]:
    return {tool.definition().name: tool for tool in ReminderSkill(repository).tools()}


def test_reminder_skill_exposes_create_and_list() -> None:
    tools = _tools(FakeReminderRepository())

    assert set(tools) == {"reminder.create", "reminder.list"}
    assert tools["reminder.create"].definition().side_effect is True
    assert tools["reminder.list"].definition().read_only is True


async def test_create_then_list_upcoming_reminders() -> None:
    repository = FakeReminderRepository()
    tools = _tools(repository)
    owner = EntityId.new()
    agent = EntityId.new()

    def context(user_id: EntityId) -> ToolContext:
        return ToolContext(
            agent_id=agent,
            agent_run_id=EntityId.new(),
            user_id=user_id,
        )

    created = await tools["reminder.create"].execute(
        {
            "title": "Llamar al dentista",
            "notes": "Pedir turno para la semana que viene",
            "remind_at": "2030-01-02T10:00:00+00:00",
        },
        context(owner),
    )
    assert created.success is True
    assert created.data["title"] == "Llamar al dentista"
    assert created.data["status"] == "PENDING"

    listed = await tools["reminder.list"].execute(
        {"upcoming_only": True}, context(owner)
    )
    assert listed.success is True
    assert listed.data["count"] == 1
    assert listed.data["items"][0]["reminder_id"] == created.data["reminder_id"]

    other_user = await tools["reminder.list"].execute(
        {"upcoming_only": True}, context(EntityId.new())
    )
    assert other_user.success is True
    assert other_user.data["count"] == 0


async def test_list_filters_by_status_and_rejects_naive_datetime() -> None:
    repository = FakeReminderRepository()
    tools = _tools(repository)
    owner = EntityId.new()
    agent = EntityId.new()

    def context() -> ToolContext:
        return ToolContext(
            agent_id=agent,
            agent_run_id=EntityId.new(),
            user_id=owner,
        )

    await tools["reminder.create"].execute(
        {"title": "Pasado", "remind_at": "2020-01-01T10:00:00+00:00"},
        context(),
    )
    await tools["reminder.create"].execute(
        {"title": "Futuro", "remind_at": "2030-01-01T10:00:00+00:00"},
        context(),
    )

    upcoming = await tools["reminder.list"].execute(
        {"upcoming_only": True}, context()
    )
    assert upcoming.data["count"] == 1
    assert upcoming.data["items"][0]["title"] == "Futuro"

    naive = await tools["reminder.create"].execute(
        {"title": "Sin zona", "remind_at": "2030-01-01T10:00:00"}, context()
    )
    assert naive.success is False
    assert naive.error_code == "REMINDER_INVALID"

    cancelled = await tools["reminder.list"].execute(
        {"status": "CANCELLED"}, context()
    )
    assert cancelled.data["count"] == 0
