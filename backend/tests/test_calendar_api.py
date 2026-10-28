from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.domain.entities.agent import Agent
from app.domain.entities.calendar_event import CalendarEvent
from app.domain.value_objects.entity_id import EntityId
from app.main import app
from app.presentation.dependencies.calendar import (
    get_calendar_agent_repository,
    get_calendar_event_repository,
)
from app.presentation.dependencies.identity import LOCAL_USER_ID

USER = EntityId(LOCAL_USER_ID)


class FakeAgentRepository:
    def __init__(self, agents: list[Agent] | None = None) -> None:
        self.agents = agents or []

    def list_by_user(self, user_id):
        return [agent for agent in self.agents if agent.user_id == user_id]


class FakeCalendarEventRepository:
    """The read the route makes, with the window rule kept honest.

    The real repository filters by overlap rather than containment, so the fake
    reproduces that: an event is in the window when it ends after the window
    opens and starts before it closes. A fake that ignored the window would let
    a route that passed the wrong argument still pass its test.
    """

    def __init__(self, events: list[CalendarEvent] | None = None) -> None:
        self.events = events or []
        self.requests: list[dict] = []

    def list_by_agent(self, agent_id, limit: int = 100, start=None, end=None):
        self.requests.append({"agent_id": agent_id, "limit": limit, "start": start, "end": end})
        selected = [
            event
            for event in self.events
            if event.agent_id == agent_id
            and (start is None or event.end_at > start)
            and (end is None or event.start_at < end)
        ]
        selected.sort(key=lambda event: event.start_at)
        return selected[:limit]


def _override(agents, events):
    app.dependency_overrides[get_calendar_agent_repository] = lambda: agents
    app.dependency_overrides[get_calendar_event_repository] = lambda: events


def teardown_function() -> None:
    for dependency in (get_calendar_agent_repository, get_calendar_event_repository):
        app.dependency_overrides.pop(dependency, None)


def _event(agent_id: EntityId, title: str, hour: int, duration_hours: int = 1) -> CalendarEvent:
    start = datetime(2026, 10, 20, hour, 0, tzinfo=UTC)
    return CalendarEvent(
        title=title,
        start_at=start,
        end_at=start.replace(hour=start.hour + duration_hours),
        agent_id=agent_id,
    )


def test_calendar_lists_the_callers_events_in_order() -> None:
    own_agent = EntityId.new()
    other_agent = EntityId.new()
    _override(
        FakeAgentRepository([Agent(id=own_agent, name="Mine", user_id=USER)]),
        FakeCalendarEventRepository(
            [
                _event(own_agent, "Tarde", 20),
                _event(own_agent, "Manana", 9),
                # Another user's agent: never read, because the route only ever
                # asks for the agents the caller owns.
                _event(other_agent, "Privado", 12),
            ]
        ),
    )

    response = TestClient(app).get("/api/v1/calendar/events")

    assert response.status_code == 200
    titles = [event["title"] for event in response.json()]
    assert titles == ["Manana", "Tarde"]


def test_calendar_never_reads_an_agent_the_caller_does_not_own() -> None:
    foreign_agent = EntityId.new()
    events = FakeCalendarEventRepository([_event(foreign_agent, "Ajeno", 10)])
    _override(FakeAgentRepository([]), events)

    response = TestClient(app).get("/api/v1/calendar/events")

    assert response.status_code == 200
    assert response.json() == []
    # The repository is not even asked: with no owned agent there is no agent id
    # to ask about, so the isolation is upstream of the query.
    assert events.requests == []


def test_calendar_window_filters_by_overlap_not_containment() -> None:
    agent_id = EntityId.new()
    _override(
        FakeAgentRepository([Agent(id=agent_id, name="Mine", user_id=USER)]),
        FakeCalendarEventRepository([_event(agent_id, "Reunion", 9, duration_hours=3)]),
    )

    # 10:00-11:00 sits inside the 09:00-12:00 event: neither edge falls in the
    # window, so a containment query would drop it.
    response = TestClient(app).get(
        "/api/v1/calendar/events"
        "?start=2026-10-20T10:00:00%2B00:00&end=2026-10-20T11:00:00%2B00:00"
    )

    assert response.status_code == 200
    assert [event["title"] for event in response.json()] == ["Reunion"]


def test_calendar_rejects_a_window_without_an_offset() -> None:
    agent_id = EntityId.new()
    _override(
        FakeAgentRepository([Agent(id=agent_id, name="Mine", user_id=USER)]),
        FakeCalendarEventRepository([_event(agent_id, "Reunion", 9)]),
    )

    response = TestClient(app).get("/api/v1/calendar/events?start=2026-10-20T10:00:00")

    assert response.status_code == 422
    assert "timezone offset" in response.json()["detail"]
