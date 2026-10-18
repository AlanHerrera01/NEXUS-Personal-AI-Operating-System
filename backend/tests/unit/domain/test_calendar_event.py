from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.domain.entities.calendar_event import CalendarEvent


def test_event_converts_an_offset_to_utc() -> None:
    event = CalendarEvent(
        title="Cita",
        start_at=datetime(2030, 1, 2, 10, 0, tzinfo=timezone(timedelta(hours=-5))),
        end_at=datetime(2030, 1, 2, 16, 0, tzinfo=UTC),
    )

    assert event.start_at == datetime(2030, 1, 2, 15, 0, tzinfo=UTC)
    assert event.start_at.tzinfo is UTC


def test_event_rejects_a_naive_start() -> None:
    with pytest.raises(ValueError, match="start must include a timezone offset"):
        CalendarEvent(
            title="Cita",
            start_at=datetime(2030, 1, 2, 10, 0),
            end_at=datetime(2030, 1, 2, 11, 0, tzinfo=UTC),
        )


def test_event_rejects_a_naive_end() -> None:
    with pytest.raises(ValueError, match="end must include a timezone offset"):
        CalendarEvent(
            title="Cita",
            start_at=datetime(2030, 1, 2, 10, 0, tzinfo=UTC),
            end_at=datetime(2030, 1, 2, 11, 0),
        )


def test_event_rejects_an_end_before_the_start() -> None:
    with pytest.raises(ValueError, match="end must be after start"):
        CalendarEvent(
            title="Cita",
            start_at=datetime(2030, 1, 2, 11, 0, tzinfo=UTC),
            end_at=datetime(2030, 1, 2, 10, 0, tzinfo=UTC),
        )


def test_event_rejects_a_zero_length_window() -> None:
    moment = datetime(2030, 1, 2, 10, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="end must be after start"):
        CalendarEvent(title="Cita", start_at=moment, end_at=moment)


def test_event_rejects_an_empty_title() -> None:
    with pytest.raises(ValueError, match="title must not be empty"):
        CalendarEvent(
            title="   ",
            start_at=datetime(2030, 1, 2, 10, 0, tzinfo=UTC),
            end_at=datetime(2030, 1, 2, 11, 0, tzinfo=UTC),
        )


def test_touch_moves_updated_at_without_touching_created_at() -> None:
    event = CalendarEvent(
        title="Cita",
        start_at=datetime(2030, 1, 2, 10, 0, tzinfo=UTC),
        end_at=datetime(2030, 1, 2, 11, 0, tzinfo=UTC),
    )
    created_at = event.created_at

    event.touch()

    assert event.updated_at >= created_at
