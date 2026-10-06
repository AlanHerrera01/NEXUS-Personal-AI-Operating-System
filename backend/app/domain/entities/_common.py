import json
from datetime import UTC, datetime
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


def require_text(value: str, field_name: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must not be empty")


def json_size(value: Any) -> int:
    """Byte length of ``value`` once encoded the way it will actually be stored.

    Deliberately not ``len(repr(value))``. ``repr`` accepts things JSON does not
    -- a ``set``, a ``datetime``, an arbitrary object -- so a payload could pass
    validation here and then fail much later when the driver tried to write it to
    a JSON column. It also measures the wrong thing: ``repr`` of a dict is
    neither the bytes stored nor a reliable proxy for them, which makes any size
    limit built on it approximate in a way that is hard to reason about.

    Raises ``TypeError`` for a value that is not JSON-serialisable, which is the
    caller's signal to reject it up front.
    """
    return len(json.dumps(value).encode("utf-8"))
