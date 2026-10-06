"""Structural plan validation.

The validator answers "is this plan well-formed and does it stay inside what the
run may touch?" It does not answer "is this action allowed?" — that is the Trust
Engine, one layer up. Keeping the two apart is what stops a planning-stage
model from deciding its own permissions.
"""

from __future__ import annotations

from typing import Sequence

from app.domain.ports.plan_validator import (
    PlanValidationResult,
    PlanValidatorPort,
    PlanViolation,
    ProposedAction,
    ProposedPlan,
)
from app.domain.value_objects.risk_level import RiskLevel

#: Argument names that let a plan reach outside the tool's own namespace.
FORBIDDEN_ARGUMENT_NAMES: frozenset[str] = frozenset(
    {
        "agent_id",
        "agent_run_id",
        "correlation_id",
        "permissions",
        "sandbox_id",
        "user_id",
        "workspace_path",
    }
)

#: Path fragments no plan may reference, whatever the tool claims to need.
FORBIDDEN_PATH_FRAGMENTS: tuple[str, ...] = (
    "~/.ssh",
    "~/.aws",
    "~/.kube",
    "/etc/shadow",
    "/etc/sudoers",
    "/var/run/docker.sock",
    "id_rsa",
    ".pem",
    "/proc/1/",
)


class DefaultPlanValidator(PlanValidatorPort):
    """Rejects unknown tools, reserved arguments, path escapes and oversized plans."""

    def __init__(self, max_actions: int = 10) -> None:
        self.max_actions = max_actions

    def validate(self, plan: ProposedPlan) -> PlanValidationResult:
        violations: list[PlanViolation] = []

        if len(plan) > self.max_actions:
            violations.append(
                PlanViolation(
                    tool_name="",
                    reason=f"plan declares {len(plan)} actions, limit is {self.max_actions}",
                )
            )

        accepted: list[ProposedAction] = []
        for action in plan.actions:
            action_violations = self._validate_action(action, plan)
            if action_violations:
                violations.extend(action_violations)
            else:
                accepted.append(action)

        return PlanValidationResult(
            valid=not any(v.severity == "BLOCK" for v in violations),
            accepted_actions=tuple(accepted),
            violations=tuple(violations),
        )

    def _validate_action(
        self, action: ProposedAction, plan: ProposedPlan
    ) -> list[PlanViolation]:
        violations: list[PlanViolation] = []

        if not action.tool_name or not action.tool_name.strip():
            return [PlanViolation(tool_name=action.tool_name, reason="tool name is empty")]

        if plan.available_tool_names and action.tool_name not in plan.available_tool_names:
            violations.append(
                PlanViolation(
                    tool_name=action.tool_name,
                    reason="tool is not available in this run",
                )
            )

        for reserved in FORBIDDEN_ARGUMENT_NAMES:
            if reserved in action.arguments:
                violations.append(
                    PlanViolation(
                        tool_name=action.tool_name,
                        reason=f"argument {reserved!r} is system-controlled and cannot be planned",
                    )
                )

        for value in _string_values(action.arguments):
            lowered = value.lower()
            for fragment in FORBIDDEN_PATH_FRAGMENTS:
                if fragment in lowered:
                    violations.append(
                        PlanViolation(
                            tool_name=action.tool_name,
                            reason="plan references a host credential or control path",
                        )
                    )
                    break

        return violations


def highest_risk(tools: Sequence[object]) -> RiskLevel:
    """Highest declared risk across a set of tool definitions."""
    highest = RiskLevel.LOW
    for definition in tools:
        risk = getattr(definition, "risk_level", None)
        if isinstance(risk, RiskLevel) and risk.value > highest.value:
            highest = risk
    return highest


def _string_values(arguments: dict) -> list[str]:
    values: list[str] = []
    for value in arguments.values():
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, (list, tuple)):
            values.extend(item for item in value if isinstance(item, str))
    return values
