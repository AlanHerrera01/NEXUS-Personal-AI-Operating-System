"""Deterministic evaluation of proactive rules.

Every condition here is arithmetic on the clock and on counts the caller already
has. There is no model call, and that is the load-bearing property rather than a
performance shortcut: a proactive system that asks an LLM "is this a good
moment to interrupt the user?" spends money on every poll, can loop forever, and
cannot be unit-tested against a known answer. Here the answer is a pure function
of ``(condition, context)``, so the interesting question becomes whether the
rule the user authored is the rule that fires.

Conditions are a closed set. An unrecognised ``type`` raises at construction of
the rule rather than silently evaluating false, because a typo that never fires
is the worst possible failure mode for a feature whose entire value is showing
up unprompted.

Each condition is written to be *true for the rest of the day* once its time
has passed, rather than true for a single instant. A scheduler that polls every
few seconds would otherwise need to hit an exact millisecond to ever fire.
``ProactiveEvaluationService`` combines this with the rule's cooldown so a
condition that stays true still only produces one trigger per cooldown window.
"""

from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.entities.proactive_rule import (
    CONDITION_DAILY_AT_TIME,
    CONDITION_DAY_OF_WEEK,
    CONDITION_IDLE_FOR,
    CONDITION_TASK_OVERDUE,
    ProactiveRule,
)
from app.domain.value_objects.entity_id import EntityId

_WEEKDAY_NAMES = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}


@dataclass(frozen=True, slots=True)
class ProactiveContext:
    """The facts a condition is allowed to look at.

    Deliberately small. Everything here is something the user could read off
    their own calendar or task list; nothing is an inference.
    """

    now: datetime
    last_activity_at: datetime | None = None
    pending_task_count: int = 0
    overdue_task_count: int = 0
    user_id: EntityId | None = None


@dataclass(frozen=True, slots=True)
class ProactiveEvaluation:
    """Outcome of testing one rule against one context."""

    matched: bool
    reason: str
    #: Present only when ``matched``. The text the rule's author wrote, which is
    #: what becomes the agent run's request or the suggestion body. It is never
    #: generated here.
    message: str | None = None


class ProactiveEvaluationError(ValueError):
    """A condition is malformed."""


def parse_clock_time(value: Any, field_name: str = "at") -> time:
    if not isinstance(value, str):
        raise ProactiveEvaluationError(f"{field_name} must be an 'HH:MM' string")
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ProactiveEvaluationError(f"{field_name} must be an 'HH:MM' string")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError as error:
        raise ProactiveEvaluationError(f"{field_name} must be an 'HH:MM' string") from error
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ProactiveEvaluationError(f"{field_name} is not a valid time of day")
    return time(hour=hour, minute=minute)


def _zone(timezone: str | None) -> ZoneInfo:
    name = timezone or "UTC"
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ProactiveEvaluationError(f"unknown IANA timezone: {name!r}") from error


class ProactiveEvaluationService:
    """Tests proactive rules against a context without a model."""

    def evaluate(self, rule: ProactiveRule, context: ProactiveContext) -> ProactiveEvaluation:
        if not rule.enabled:
            return ProactiveEvaluation(False, "rule is disabled")
        if rule.cooldown_active(context.now):
            return ProactiveEvaluation(False, "rule fired within its cooldown window")

        handler = self._handlers.get(rule.condition.get("type"))
        if handler is None:
            # Unreachable: ProactiveRule.__post_init__ rejects unknown types.
            raise ProactiveEvaluationError(
                f"unsupported condition type: {rule.condition.get('type')!r}"
            )

        matched, reason = handler(rule.condition, context)
        return ProactiveEvaluation(matched, reason, message=rule.message if matched else None)

    # -- condition handlers ----------------------------------------------

    def _daily_at_time(
        self, condition: dict[str, Any], context: ProactiveContext
    ) -> tuple[bool, str]:
        target = parse_clock_time(condition.get("at"))
        local = context.now.astimezone(_zone(condition.get("timezone")))
        if local.time() >= target:
            return True, f"local time {local.strftime('%H:%M')} is at or past {target.strftime('%H:%M')}"
        return False, f"local time {local.strftime('%H:%M')} is before {target.strftime('%H:%M')}"

    def _day_of_week(
        self, condition: dict[str, Any], context: ProactiveContext
    ) -> tuple[bool, str]:
        raw_days = condition.get("days")
        if not isinstance(raw_days, (list, tuple)) or not raw_days:
            raise ProactiveEvaluationError("DAY_OF_WEEK requires a non-empty 'days' list")

        wanted: set[int] = set()
        for entry in raw_days:
            key = str(entry).strip().lower()
            if key not in _WEEKDAY_NAMES:
                raise ProactiveEvaluationError(
                    f"DAY_OF_WEEK got an unknown day: {entry!r}"
                )
            wanted.add(_WEEKDAY_NAMES[key])

        local = context.now.astimezone(_zone(condition.get("timezone")))
        # Monday==0 here, matching the rule vocabulary rather than datetime.weekday.
        if local.weekday() not in wanted:
            return False, f"{local.strftime('%A')} is not one of the configured days"

        if "at" in condition:
            target = parse_clock_time(condition.get("at"))
            if local.time() < target:
                return False, (
                    f"local time {local.strftime('%H:%M')} is before {target.strftime('%H:%M')}"
                )
        return True, f"{local.strftime('%A')} is a configured day and the time has passed"

    def _idle_for(
        self, condition: dict[str, Any], context: ProactiveContext
    ) -> tuple[bool, str]:
        raw_minutes = condition.get("minutes")
        if not isinstance(raw_minutes, int) or isinstance(raw_minutes, bool):
            raise ProactiveEvaluationError("IDLE_FOR requires an integer 'minutes'")
        if raw_minutes <= 0:
            raise ProactiveEvaluationError("IDLE_FOR 'minutes' must be greater than zero")

        if context.last_activity_at is None:
            # No recorded activity is not evidence of inactivity; treating it as
            # idle would fire a rule on a brand new account every cycle.
            return False, "no recorded activity to judge idleness against"
        idle_seconds = (context.now - context.last_activity_at).total_seconds()
        if idle_seconds >= raw_minutes * 60:
            return True, f"idle for {int(idle_seconds // 60)} minutes"
        return False, f"idle for {int(idle_seconds // 60)} of {raw_minutes} minutes"

    def _task_overdue(
        self, condition: dict[str, Any], context: ProactiveContext
    ) -> tuple[bool, str]:
        threshold = condition.get("min_count", 1)
        if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 1:
            raise ProactiveEvaluationError("TASK_OVERDUE 'min_count' must be a positive integer")
        if context.overdue_task_count >= threshold:
            return True, f"{context.overdue_task_count} overdue task(s)"
        return False, f"no overdue tasks (threshold {threshold})"

    @property
    def _handlers(self) -> dict[str, Any]:
        return {
            CONDITION_DAILY_AT_TIME: self._daily_at_time,
            CONDITION_DAY_OF_WEEK: self._day_of_week,
            CONDITION_IDLE_FOR: self._idle_for,
            CONDITION_TASK_OVERDUE: self._task_overdue,
        }