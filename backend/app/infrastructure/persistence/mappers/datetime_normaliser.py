"""Datetime normalisation shared by the persistence adapters.

Several drivers -- SQLite in particular, and some Postgres configurations --
return a naive ``datetime`` even for a ``DateTime(timezone=True)`` column. The
Always-On entities reject naive datetimes outright (a naive ``next_run_at`` is
genuinely ambiguous, and quietly assuming UTC for it is how a job ends up firing
an hour off), so every adapter has to normalise on the way out.

Re-attaching UTC is correct for these columns specifically because every value
written to them was already converted to UTC by the domain. This is not a
general-purpose "assume UTC" helper and is not safe on columns holding local
wall-clock time.
"""

from datetime import UTC, datetime


def ensure_utc(value: datetime | None) -> datetime | None:
    """Attach UTC to a naive datetime, leave an aware one alone."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)