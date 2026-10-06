"""A user-authored rule that lets NEXUS speak first.

The whole point of this entity is restraint. A proactive rule is something the
user declared in advance -- "if it is past 17:00 and nothing is logged today,
nudge me" -- and it may only ever do one of two things:

* raise a **suggestion** for the user to accept, or
* trigger an agent run whose ``user_request`` is the text the user themselves
  authored in the rule.

There is no third kind where the rule decides on its own to do something. A
rule carries no permission, no standing grant and no tool authorization; if the
run it triggers needs approval, the run stops in ``WAITING_PERMISSION`` exactly
as if a human had typed the request. That is why ``condition`` and ``action``
are validated against closed vocabularies instead of being free-form payloads:
an unrecognised key is a configuration error, not a hook for something the user
did not intend to author.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.domain.entities._common import json_size, require_text, utc_now
from app.domain.value_objects.entity_id import EntityId

MAX_RULE_NAME_LENGTH = 200
MAX_PROMPT_LENGTH = 2_000
MAX_CONDITION_BYTES = 4_096

#: Closed vocabulary for ``action["type"]``.
ACTION_SUGGEST = "SUGGEST"
ACTION_RUN_AGENT = "RUN_AGENT"
ALLOWED_ACTION_TYPES = frozenset({ACTION_SUGGEST, ACTION_RUN_AGENT})

#: Closed vocabulary for ``condition["type"]``. Each is evaluated by
#: :class:`ProactiveEvaluationService` with no model involved.
CONDITION_DAILY_AT_TIME = "DAILY_AT_TIME"
CONDITION_DAY_OF_WEEK = "DAY_OF_WEEK"
CONDITION_IDLE_FOR = "IDLE_FOR"
CONDITION_TASK_OVERDUE = "TASK_OVERDUE"
ALLOWED_CONDITION_TYPES = frozenset(
    {
        CONDITION_DAILY_AT_TIME,
        CONDITION_DAY_OF_WEEK,
        CONDITION_IDLE_FOR,
        CONDITION_TASK_OVERDUE,
    }
)


class ProactiveRuleError(ValueError):
    """The rule is malformed or asks for something outside its authority."""


@dataclass
class ProactiveRule:
    """A user's standing permission to be nudged under stated conditions."""

    user_id: EntityId
    agent_id: EntityId
    name: str
    condition: dict[str, Any]
    action: dict[str, Any]
    id: EntityId = field(default_factory=EntityId.new)
    enabled: bool = True
    cooldown_seconds: int = 3_600
    last_triggered_at: datetime | None = None
    trigger_count: int = 0
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        require_text(self.name, "name")
        if len(self.name) > MAX_RULE_NAME_LENGTH:
            raise ProactiveRuleError(f"name exceeds {MAX_RULE_NAME_LENGTH} characters")
        _validate_mapping(self.condition, "condition", MAX_CONDITION_BYTES)
        _validate_mapping(self.action, "action", MAX_CONDITION_BYTES)
        if self.cooldown_seconds < 0:
            raise ProactiveRuleError("cooldown_seconds must not be negative")
        if self.trigger_count < 0:
            raise ProactiveRuleError("trigger_count must not be negative")
        for field_name in ("last_triggered_at", "created_at", "updated_at"):
            moment = getattr(self, field_name)
            if moment is not None and moment.tzinfo is None:
                raise ProactiveRuleError(f"{field_name} must be timezone-aware")

        condition_type = self.condition.get("type")
        if condition_type not in ALLOWED_CONDITION_TYPES:
            raise ProactiveRuleError(
                f"condition type must be one of "
                f"{sorted(ALLOWED_CONDITION_TYPES)}, got {condition_type!r}"
            )

        action_type = self.action.get("type")
        if action_type not in ALLOWED_ACTION_TYPES:
            raise ProactiveRuleError(
                f"action type must be one of {sorted(ALLOWED_ACTION_TYPES)}, "
                f"got {action_type!r}"
            )

        message = self.action.get("message")
        require_text(message, "action.message")
        if len(message) > MAX_PROMPT_LENGTH:
            raise ProactiveRuleError(
                f"action.message exceeds {MAX_PROMPT_LENGTH} characters"
            )

    # -- lifecycle -------------------------------------------------------

    def enable(self) -> "ProactiveRule":
        self.enabled = True
        self.updated_at = utc_now()
        return self

    def disable(self) -> "ProactiveRule":
        self.enabled = False
        self.updated_at = utc_now()
        return self

    def record_trigger(self, now: datetime) -> "ProactiveRule":
        self.last_triggered_at = now
        self.trigger_count += 1
        self.updated_at = now
        return self

    def cooldown_active(self, now: datetime) -> bool:
        """True when the rule fired too recently to fire again.

        Checked by the evaluation service before anything is emitted, so a rule
        that matches continuously cannot become a message generator.
        """
        if self.last_triggered_at is None or self.cooldown_seconds == 0:
            return False
        return (now - self.last_triggered_at).total_seconds() < self.cooldown_seconds

    def is_owned_by(self, user_id: EntityId) -> bool:
        return self.user_id == user_id

    def assert_owned_by(self, user_id: EntityId) -> None:
        if not self.is_owned_by(user_id):
            raise PermissionError("proactive rule belongs to another user")

    @property
    def action_type(self) -> str:
        return self.action["type"]

    @property
    def message(self) -> str:
        return self.action["message"]


def _validate_mapping(value: Any, field_name: str, max_bytes: int) -> None:
    if not isinstance(value, dict):
        raise ProactiveRuleError(f"{field_name} must be a mapping")
    try:
        size = json_size(value)
    except (TypeError, ValueError) as error:
        raise ProactiveRuleError(f"{field_name} is not serialisable: {error}") from error
    if size > max_bytes:
        raise ProactiveRuleError(
            f"{field_name} is {size} bytes which exceeds the {max_bytes} byte limit"
        )