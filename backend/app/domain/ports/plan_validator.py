"""Plan validation: the gate between the planner and the Trust Engine.

A model may propose anything. The validator checks the proposal against the
run's declared tools, the skill catalog and hard safety rules, and can only
narrow what the plan is allowed to do. It never authorizes: authorization is the
Trust Engine's job, and only the Trust Engine's job.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.risk_level import RiskLevel


@dataclass(frozen=True, slots=True)
class ProposedAction:
    """One step a plan wants to take, before any authorization has happened."""

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""


@dataclass(frozen=True, slots=True)
class ProposedPlan:
    """A planner's output, structurally validated but not yet authorized."""

    agent_id: EntityId
    agent_run_id: EntityId
    actions: tuple[ProposedAction, ...] = ()
    available_tool_names: frozenset[str] = frozenset()

    def __len__(self) -> int:
        return len(self.actions)


@dataclass(frozen=True, slots=True)
class PlanViolation:
    tool_name: str
    reason: str
    severity: str = "BLOCK"


@dataclass(frozen=True, slots=True)
class PlanValidationResult:
    valid: bool
    accepted_actions: tuple[ProposedAction, ...] = ()
    violations: tuple[PlanViolation, ...] = ()

    def __bool__(self) -> bool:
        return self.valid

    @property
    def blocking_violations(self) -> tuple[PlanViolation, ...]:
        return tuple(v for v in self.violations if v.severity == "BLOCK")


class PlanValidatorPort(ABC):
    @abstractmethod
    def validate(self, plan: ProposedPlan) -> PlanValidationResult:
        raise NotImplementedError


def declared_risk(plan: ProposedPlan, lookup: Any) -> RiskLevel:
    """Highest risk declared across a plan, given a tool-definition lookup."""
    highest = RiskLevel.LOW
    for action in plan.actions:
        definition = lookup(action.tool_name)
        if definition is not None and definition.risk_level is not None:
            if definition.risk_level.value > highest.value:
                highest = definition.risk_level
    return highest


__all__: Sequence[str] = (
    "PlanValidationResult",
    "PlanValidatorPort",
    "PlanViolation",
    "ProposedAction",
    "ProposedPlan",
    "declared_risk",
)
