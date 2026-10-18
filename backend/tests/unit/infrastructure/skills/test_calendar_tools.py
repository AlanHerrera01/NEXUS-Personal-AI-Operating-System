import asyncio
from datetime import UTC, datetime

import pytest

from app.domain.ports.tool import ToolContext
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.risk_level import RiskLevel
from app.domain.value_objects.tool_error_code import ToolErrorCode
from app.infrastructure.skills.calendar.skill import CalendarSkill
from app.infrastructure.skills.calendar.tools.create_event import CreateCalendarEventTool
from app.infrastructure.skills.calendar.tools.list_events import ListCalendarEventsTool
from tests.support.repositories import (
    FakeCalendarEventRepository,
    FailingCalendarEventRepository,
    make_event,
)


@pytest.fixture
def repository() -> FakeCalendarEventRepository:
    return FakeCalendarEventRepository()


@pytest.fixture
def context() -> ToolContext:
    return ToolContext(agent_id=EntityId.new(), agent_run_id=EntityId.new())


def run(coroutine):
    return asyncio.run(coroutine)


def test_skill_exposes_two_namespaced_tools(repository: FakeCalendarEventRepository) -> None:
    skill = CalendarSkill(repository)

    definition = skill.definition()

    assert definition.name == "calendar"
    assert definition.enabled is True
    assert [tool.definition().name for tool in skill.tools()] == [
        "calendar.create_event",
        "calendar.list_events",
    ]
    assert all(tool.definition().skill_name == "calendar" for tool in skill.tools())


def test_tool_metadata_declares_risk_and_side_effects(repository: FakeCalendarEventRepository) -> None:
    tools = {tool.definition().name: tool.definition() for tool in CalendarSkill(repository).tools()}

    assert tools["calendar.list_events"].read_only is True
    assert tools["calendar.list_events"].side_effect is False
    assert tools["calendar.create_event"].read_only is False
    assert tools["calendar.create_event"].side_effect is True
    # A write to a calendar is the user's own time being spent, so the gate stays.
    assert tools["calendar.create_event"].requires_confirmation is True
    assert tools["calendar.create_event"].risk_level is RiskLevel.LOW
    assert all(definition.input_schema["additionalProperties"] is False for definition in tools.values())


def test_create_persists_through_the_use_case(
    repository: FakeCalendarEventRepository, context: ToolContext
) -> None:
    result = run(
        CreateCalendarEventTool(repository).execute(
            {
                "title": "Revision de arquitectura",
                "start": "2030-01-02T10:00:00+00:00",
                "end": "2030-01-02T11:30:00+00:00",
                "location": "Sala 2",
            },
            context,
        )
    )

    assert result.success is True
    assert result.tool_name == "calendar.create_event"
    assert result.data["title"] == "Revision de arquitectura"
    assert result.data["location"] == "Sala 2"
    assert len(repository.items) == 1
    assert result.metadata["skill"] == "calendar"


def test_create_stores_the_instant_in_utc(
    repository: FakeCalendarEventRepository, context: ToolContext
) -> None:
    result = run(
        CreateCalendarEventTool(repository).execute(
            {"title": "Cita", "start": "2030-01-02T10:00:00-05:00", "end": "2030-01-02T11:00:00-05:00"},
            context,
        )
    )

    assert result.success is True
    assert result.data["start_at"].startswith("2030-01-02T15:00:00")
    assert result.data["end_at"].startswith("2030-01-02T16:00:00")


def test_create_rejects_a_datetime_without_an_offset(
    repository: FakeCalendarEventRepository, context: ToolContext
) -> None:
    result = run(
        CreateCalendarEventTool(repository).execute(
            {"title": "Cita", "start": "2030-01-02T10:00:00", "end": "2030-01-02T11:00:00"},
            context,
        )
    )

    assert result.success is False
    assert result.error_code == ToolErrorCode.CALENDAR_EVENT_INVALID
    assert "start" in result.error_message
    assert repository.items == {}


def test_create_rejects_an_end_before_the_start(
    repository: FakeCalendarEventRepository, context: ToolContext
) -> None:
    result = run(
        CreateCalendarEventTool(repository).execute(
            {"title": "Cita", "start": "2030-01-02T11:00:00+00:00", "end": "2030-01-02T10:00:00+00:00"},
            context,
        )
    )

    assert result.success is False
    assert result.error_code == ToolErrorCode.CALENDAR_EVENT_INVALID
    assert repository.items == {}


def test_create_rejects_a_missing_start(repository: FakeCalendarEventRepository, context: ToolContext) -> None:
    result = run(CreateCalendarEventTool(repository).execute({"title": "Sin hora"}, context))

    assert result.success is False
    assert result.error_code == ToolErrorCode.INVALID_ARGUMENTS
    assert "start" in result.error_message


def test_create_rejects_unknown_arguments(
    repository: FakeCalendarEventRepository, context: ToolContext
) -> None:
    result = run(
        CreateCalendarEventTool(repository).execute(
            {"title": "x", "start": "2030-01-02T10:00:00+00:00", "end": "2030-01-02T11:00:00+00:00", "owner": "root"},
            context,
        )
    )

    assert result.success is False
    assert result.error_code == ToolErrorCode.INVALID_ARGUMENTS


def test_create_rejects_identity_arguments_from_the_model(
    repository: FakeCalendarEventRepository, context: ToolContext
) -> None:
    result = run(
        CreateCalendarEventTool(repository).execute(
            {
                "title": "x",
                "start": "2030-01-02T10:00:00+00:00",
                "end": "2030-01-02T11:00:00+00:00",
                "agent_id": str(EntityId.new()),
            },
            context,
        )
    )

    assert result.success is False
    assert result.error_code == ToolErrorCode.FORBIDDEN_ARGUMENTS
    assert repository.items == {}


def test_create_reports_repository_failures_without_leaking_internals(context: ToolContext) -> None:
    result = run(
        CreateCalendarEventTool(FailingCalendarEventRepository()).execute(
            {"title": "x", "start": "2030-01-02T10:00:00+00:00", "end": "2030-01-02T11:00:00+00:00"},
            context,
        )
    )

    assert result.success is False
    assert result.error_code == ToolErrorCode.TOOL_EXECUTION_FAILED
    assert "Traceback" not in result.error_message
    assert "connection reset" not in result.error_message


def test_list_only_returns_events_of_the_context_agent(
    repository: FakeCalendarEventRepository, context: ToolContext
) -> None:
    repository.save(make_event(context.agent_id, "Mine"))
    repository.save(make_event(EntityId.new(), "Not mine"))

    result = run(ListCalendarEventsTool(repository).execute({}, context))

    assert result.success is True
    assert result.data["count"] == 1
    assert result.data["items"][0]["title"] == "Mine"


def test_list_includes_events_that_overlap_the_window(
    repository: FakeCalendarEventRepository, context: ToolContext
) -> None:
    # 09:00-12:00 against a 10:00-11:00 question: neither edge falls inside the
    # window, so a containment query would drop it.
    repository.save(
        make_event(
            context.agent_id,
            "Larga",
            start_at=datetime(2030, 1, 2, 9, 0, tzinfo=UTC),
            end_at=datetime(2030, 1, 2, 12, 0, tzinfo=UTC),
        )
    )

    result = run(
        ListCalendarEventsTool(repository).execute(
            {"start": "2030-01-02T10:00:00+00:00", "end": "2030-01-02T11:00:00+00:00"}, context
        )
    )

    assert result.success is True
    assert result.data["count"] == 1
    assert result.data["items"][0]["title"] == "Larga"


def test_list_excludes_events_outside_the_window(
    repository: FakeCalendarEventRepository, context: ToolContext
) -> None:
    repository.save(
        make_event(
            context.agent_id,
            "Ayer",
            start_at=datetime(2030, 1, 1, 9, 0, tzinfo=UTC),
            end_at=datetime(2030, 1, 1, 10, 0, tzinfo=UTC),
        )
    )

    result = run(
        ListCalendarEventsTool(repository).execute(
            {"start": "2030-01-02T00:00:00+00:00", "end": "2030-01-03T00:00:00+00:00"}, context
        )
    )

    assert result.success is True
    assert result.data["count"] == 0
    assert result.data["items"] == []


def test_list_returns_events_in_chronological_order(
    repository: FakeCalendarEventRepository, context: ToolContext
) -> None:
    repository.save(
        make_event(
            context.agent_id,
            "Tarde",
            start_at=datetime(2030, 1, 2, 16, 0, tzinfo=UTC),
            end_at=datetime(2030, 1, 2, 17, 0, tzinfo=UTC),
        )
    )
    repository.save(
        make_event(
            context.agent_id,
            "Manana",
            start_at=datetime(2030, 1, 2, 9, 0, tzinfo=UTC),
            end_at=datetime(2030, 1, 2, 10, 0, tzinfo=UTC),
        )
    )

    result = run(ListCalendarEventsTool(repository).execute({}, context))

    assert [item["title"] for item in result.data["items"]] == ["Manana", "Tarde"]


def test_list_rejects_an_inverted_window(
    repository: FakeCalendarEventRepository, context: ToolContext
) -> None:
    result = run(
        ListCalendarEventsTool(repository).execute(
            {"start": "2030-01-02T11:00:00+00:00", "end": "2030-01-02T10:00:00+00:00"}, context
        )
    )

    assert result.success is False
    assert result.error_code == ToolErrorCode.CALENDAR_EVENT_INVALID


def test_list_rejects_an_out_of_range_limit(
    repository: FakeCalendarEventRepository, context: ToolContext
) -> None:
    result = run(ListCalendarEventsTool(repository).execute({"limit": 10_000}, context))

    assert result.success is False
    assert result.error_code == ToolErrorCode.INVALID_ARGUMENTS


def test_list_is_empty_without_events(repository: FakeCalendarEventRepository, context: ToolContext) -> None:
    result = run(ListCalendarEventsTool(repository).execute({}, context))

    assert result.success is True
    assert result.data == {"items": [], "count": 0}


def test_tools_never_call_the_llm_or_the_orchestrator() -> None:
    import inspect

    for module in (
        "app.infrastructure.skills.calendar.tools.create_event",
        "app.infrastructure.skills.calendar.tools.list_events",
    ):
        source = inspect.getsource(__import__(module, fromlist=["*"]))
        assert "llm" not in source.lower()
        assert "orchestrator" not in source.lower()
        assert "subprocess" not in source.lower()
        assert "eval(" not in source
        assert "exec(" not in source
