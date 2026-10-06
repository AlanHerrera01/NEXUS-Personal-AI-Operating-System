from app.application.security.policy_engine import PolicyEngine
from app.domain.ports.tool import ToolDefinition
from app.domain.repositories.permission_repository import PermissionRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_decision import PermissionDecision
from app.domain.value_objects.risk_level import RiskLevel
from app.domain.value_objects.trust_context import TrustContext
from app.domain.value_objects.trust_evaluation import TrustEvaluation


class TrustEngine:
    """Coordinates policy evaluation, permission checking, and trust decisions."""

    def __init__(
        self,
        policy_engine: PolicyEngine,
        permission_repository: PermissionRepository,
        default_decision: PermissionDecision = PermissionDecision.DENY,
    ) -> None:
        self.policy_engine = policy_engine
        self.permission_repository = permission_repository
        self.default_decision = default_decision

    def evaluate(
        self,
        tool: ToolDefinition,
        user_id: EntityId | None,
        agent_id: EntityId,
        agent_run_id: EntityId,
        arguments: dict,
    ) -> TrustEvaluation:
        """Evaluate a tool call against policies and permissions."""
        # Create trust context
        context = TrustContext(
            user_id=user_id,
            agent_id=agent_id,
            agent_run_id=agent_run_id,
            tool_name=tool.name,
            skill_name=tool.skill_name,
            risk_level=tool.risk_level,
            read_only=tool.read_only,
            side_effect=tool.side_effect,
            arguments=arguments,
            tool_metadata={
                "requires_confirmation": tool.requires_confirmation,
                "category": tool.category,
                "version": tool.version,
                "tags": tool.tags,
            },
        )

        # Evaluate policies
        policy_result = self.policy_engine.evaluate(context)

        # Convert policy result to trust evaluation
        if not policy_result.applicable:
            # Default deny if no policies apply
            return TrustEvaluation(
                decision=self.default_decision,
                risk_level=context.risk_level,
                reason="No applicable policy found - default deny",
                policy_id="default_deny",
                requires_confirmation=False,
            )

        requires_confirmation = bool(tool.requires_confirmation)
        decision = policy_result.decision
        reason = policy_result.reason
        policy_id = policy_result.policy_id

        # Invariant guard. A tool that declares requires_confirmation must never
        # execute unattended, whatever any policy concluded. Applied here rather
        # than trusted to each policy, so adding a policy cannot bypass it.
        if decision is PermissionDecision.ALLOW and requires_confirmation:
            decision = PermissionDecision.ASK
            reason = f"Tool '{tool.name}' requires confirmation"

        return TrustEvaluation(
            decision=decision,
            risk_level=context.risk_level,
            reason=reason,
            policy_id=policy_id,
            requires_confirmation=requires_confirmation
            or decision is PermissionDecision.ASK,
        )

    def check_permission(
        self,
        user_id: EntityId,
        agent_id: EntityId,
        skill_name: str,
        action_name: str,
    ) -> bool:
        """Check if a user/agent has a specific permission."""
        return self.permission_repository.check_permission(user_id, agent_id, skill_name, action_name)
