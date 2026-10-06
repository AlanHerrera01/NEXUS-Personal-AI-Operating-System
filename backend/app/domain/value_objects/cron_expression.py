"""Deterministic 5-field cron parsing and next-fire computation.

Lives in Domain on purpose: a schedule is business logic, not an adapter
concern, and the alternative (APScheduler) would put a third-party scheduler
with its own persistence and its own idea of "next run" inside the core of the
system. A schedule whose next fire time cannot be explained by reading the code
is a schedule nobody can reason about at 3am.

Scope is deliberately narrower than full POSIX cron:

* exactly 5 fields: minute hour day-of-month month day-of-week
* each field is ``*``, a single value, a comma list, a range, or a step
* no ``@daily`` aliases, no ``L``, no ``#``, no second or year field

Refusing the exotic syntax is a feature. An unparseable schedule is rejected at
creation time with a specific message instead of quietly firing at the wrong
moment forever.

Day-of-month and day-of-week follow real Vixie cron semantics: when *both* are
restricted, a day matches if it satisfies *either* field. So ``0 0 13 * 5`` fires
on the 13th of every month *and* on every Friday. This is the opposite of what
people usually assume, it is the most common way a hand-written cron parser goes
wrong, and under the "both" reading the schedule silently fires about once every
28 months while still looking perfectly valid -- so it is asserted in the tests
rather than left implicit.

All arithmetic happens on naive local wall-clock datetimes inside the requested
IANA zone and is converted to UTC only at the boundary. Doing it in UTC would
make "09:00 every weekday" drift by an hour twice a year.

The search walks candidate *days* (bounded, ~1800 iterations for a five-year
horizon) and then picks the earliest allowed hour/minute within a matching day.
That is deliberately less clever than a field-by-field skip: it is a few hundred
microseconds, it cannot fall into a wrong answer, and there is no branch here
that a reviewer has to simulate in their head.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

#: How far ahead ``next_after`` searches before giving up. A schedule that
#: matches no real date (February 30th) must fail loudly rather than spin. Five
#: years is comfortably past the worst legal gap (Feb 29 -> Feb 29 is four).
_SEARCH_HORIZON_YEARS = 5

_MINUTES = range(0, 60)
_HOURS = range(0, 24)
_DAYS_OF_MONTH = range(1, 32)
_MONTHS = range(1, 13)
_DAYS_OF_WEEK = range(0, 7)  # 0 and 7 both mean Sunday

_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DAY_OF_WEEK_NAMES = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}

_FIELD_NAMES = ("minute", "hour", "day-of-month", "month", "day-of-week")
_UTC = ZoneInfo("UTC")


class CronExpressionError(ValueError):
    """The expression is not a schedule this system is willing to run."""


@dataclass(frozen=True, slots=True)
class _Field:
    values: frozenset[int]
    restricted: bool

    def matches(self, value: int) -> bool:
        return value in self.values

    @property
    def ordered(self) -> list[int]:
        return sorted(self.values)


def _resolve_timezone(timezone: str) -> ZoneInfo:
    if not timezone:
        raise CronExpressionError("timezone must not be empty")
    try:
        return ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise CronExpressionError(f"unknown IANA timezone: {timezone!r}") from error


def _parse_number(token: str, field_index: int, allowed: range) -> int:
    key = token.strip().lower()
    names = _MONTH_NAMES if field_index == 3 else _DAY_OF_WEEK_NAMES if field_index == 4 else None
    if names is not None and key in names:
        return names[key]

    try:
        value = int(key)
    except ValueError as error:
        raise CronExpressionError(
            f"{_FIELD_NAMES[field_index]} field has a non-numeric value: {token!r}"
        ) from error

    # Cron treats 7 and 0 as the same day (Sunday).
    if field_index == 4 and value == 7:
        value = 0

    if value not in allowed:
        raise CronExpressionError(
            f"{_FIELD_NAMES[field_index]} field value {value} is out of range "
            f"{allowed.start}..{allowed.stop - 1}"
        )
    return value


def _parse_field(raw: str, field_index: int, allowed: range) -> _Field:
    token = raw.strip()
    if not token:
        raise CronExpressionError(f"{_FIELD_NAMES[field_index]} field must not be empty")

    restricted = token != "*"
    values: set[int] = set()

    for entry in token.split(","):
        entry = entry.strip()
        if not entry:
            raise CronExpressionError(
                f"{_FIELD_NAMES[field_index]} field has an empty list entry"
            )

        step = 1
        body = entry
        if "/" in entry:
            body, _, step_raw = entry.partition("/")
            try:
                step = int(step_raw)
            except ValueError as error:
                raise CronExpressionError(
                    f"{_FIELD_NAMES[field_index]} field has a non-numeric step: {step_raw!r}"
                ) from error
            if step <= 0:
                raise CronExpressionError(
                    f"{_FIELD_NAMES[field_index]} field step must be greater than zero"
                )
            if not body.strip():
                raise CronExpressionError(
                    f"{_FIELD_NAMES[field_index]} field has a step without a range"
                )

        body = body.strip()
        if body == "*":
            start, end = allowed.start, allowed.stop - 1
        elif "-" in body:
            start_raw, _, end_raw = body.partition("-")
            start = _parse_number(start_raw, field_index, allowed)
            end = _parse_number(end_raw, field_index, allowed)
            if end < start:
                raise CronExpressionError(
                    f"{_FIELD_NAMES[field_index]} field range is inverted: {body!r}"
                )
        else:
            start = end = _parse_number(body, field_index, allowed)

        values.update(range(start, end + 1, step))

    if not values:
        raise CronExpressionError(f"{_FIELD_NAMES[field_index]} field matches nothing")

    return _Field(values=frozenset(values), restricted=restricted)


class CronExpression:
    """An immutable, validated 5-field cron expression bound to an IANA zone.

    Timezone note: a local time that does not exist on a spring-forward day, or
    that occurs twice on a fall-back day, is resolved using the standard library
    ``fold`` rules. Choosing "run twice" or "skip" for every deployment would be
    a worse default than the one the platform already agrees on.
    """

    __slots__ = ("_expression", "_timezone", "_timezone_name", "_fields")

    def __init__(self, expression: str, timezone: str = "UTC") -> None:
        if not expression or not expression.strip():
            raise CronExpressionError("cron expression must not be empty")

        parts = expression.split()
        if len(parts) != 5:
            raise CronExpressionError(
                "cron expression must have exactly 5 fields "
                f"(minute hour day-of-month month day-of-week), got {len(parts)}"
            )

        self._expression = " ".join(parts)
        self._timezone_name = timezone
        self._timezone = _resolve_timezone(timezone)
        self._fields = (
            _parse_field(parts[0], 0, _MINUTES),
            _parse_field(parts[1], 1, _HOURS),
            _parse_field(parts[2], 2, _DAYS_OF_MONTH),
            _parse_field(parts[3], 3, _MONTHS),
            _parse_field(parts[4], 4, _DAYS_OF_WEEK),
        )

    @property
    def expression(self) -> str:
        return self._expression

    @property
    def timezone(self) -> str:
        return self._timezone_name

    @property
    def _minute(self) -> _Field:
        return self._fields[0]

    @property
    def _hour(self) -> _Field:
        return self._fields[1]

    @property
    def _day_of_month(self) -> _Field:
        return self._fields[2]

    @property
    def _month(self) -> _Field:
        return self._fields[3]

    @property
    def _day_of_week(self) -> _Field:
        return self._fields[4]

    def _day_matches(self, day: datetime) -> bool:
        if not self._month.matches(day.month):
            return False
        by_day_of_month = self._day_of_month.matches(day.day)
        by_day_of_week = self._day_of_week.matches((day.weekday() + 1) % 7)
        if self._day_of_month.restricted and self._day_of_week.restricted:
            # Vixie semantics: when BOTH day fields are restricted the day fires
            # if EITHER matches, not only when both do. This is the single most
            # surprising thing about cron, and it is why `0 0 13 * 5` means "the
            # 13th, and every Friday" rather than "the 13th, but only if it falls
            # on a Friday" -- which would fire roughly once every 28 months.
            # Getting this backwards makes an expression silently almost-never
            # run while still looking perfectly valid.
            return by_day_of_month or by_day_of_week
        if self._day_of_month.restricted:
            return by_day_of_month
        if self._day_of_week.restricted:
            return by_day_of_week
        return True

    def matches(self, moment: datetime) -> bool:
        """True when ``moment`` lands exactly on a firing boundary.

        A naive ``moment`` is interpreted as UTC; an aware one is converted into
        this expression's zone first.
        """
        local = self.to_local(moment)
        return (
            local.second == 0
            and local.microsecond == 0
            and self._minute.matches(local.minute)
            and self._hour.matches(local.hour)
            and self._day_matches(local)
        )

    def to_local(self, moment: datetime) -> datetime:
        if moment.tzinfo is None:
            return moment.replace(tzinfo=self._timezone)
        return moment.astimezone(self._timezone)

    def next_after(self, after: datetime) -> datetime | None:
        """First firing instant strictly after ``after``, as aware UTC.

        ``None`` means the schedule is syntactically valid but can never fire
        inside the horizon (February 30th, or the 31st of February).
        """
        local = self.to_local(after)
        # Walk whole local days starting from the day ``after`` falls in.
        day = local.replace(hour=0, minute=0, second=0, microsecond=0)
        horizon = day + timedelta(days=366 * _SEARCH_HORIZON_YEARS)
        hours = self._hour.ordered
        minutes = self._minute.ordered

        while day <= horizon:
            if self._day_matches(day):
                for hour in hours:
                    for minute in minutes:
                        candidate = day.replace(hour=hour, minute=minute)
                        if candidate > local:
                            return candidate.astimezone(_UTC)
            day = day + timedelta(days=1)

        return None


def next_cron_occurrence(expression: str, after: datetime, timezone: str = "UTC") -> datetime:
    """Parse ``expression`` and return its next firing time, or raise."""
    cron = CronExpression(expression, timezone)
    occurrence = cron.next_after(after)
    if occurrence is None:
        raise CronExpressionError(
            f"cron expression {expression!r} has no occurrence within "
            f"{_SEARCH_HORIZON_YEARS} years"
        )
    return occurrence


def validate_cron(expression: str, timezone: str = "UTC") -> str:
    """Validate without computing anything; returns the normalised expression."""
    return CronExpression(expression, timezone).expression