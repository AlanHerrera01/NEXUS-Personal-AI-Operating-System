from dataclasses import dataclass

from app.domain.value_objects.permission_decision import PermissionDecision


@dataclass(frozen=True)
class PolicyResult:
    applicable: bool
    decision: PermissionDecision
    reason: str
    policy_id: str

    @classmethod
    def not_applicable(cls, policy_id: str) -> "PolicyResult":
        return cls(applicable=False, decision=PermissionDecision.ALLOW, reason="", policy_id=policy_id)

    @classmethod
    def allow(cls, policy_id: str, reason: str) -> "PolicyResult":
        return cls(applicable=True, decision=PermissionDecision.ALLOW, reason=reason, policy_id=policy_id)

    @classmethod
    def ask(cls, policy_id: str, reason: str) -> "PolicyResult":
        return cls(applicable=True, decision=PermissionDecision.ASK, reason=reason, policy_id=policy_id)

    @classmethod
    def deny(cls, policy_id: str, reason: str) -> "PolicyResult":
        return cls(applicable=True, decision=PermissionDecision.DENY, reason=reason, policy_id=policy_id)
