from app.application.security.trust_engine import TrustEngine
from app.domain.ports.tool import ToolDefinition
from app.domain.repositories.permission_repository import PermissionRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.permission_decision import PermissionDecision
from app.domain.value_objects.trust_evaluation import TrustEvaluation


class DeterministicTrustEngine(TrustEngine):
    """In-process Trust Engine bound to the default policy set.

    Naming is historical: the engine is deterministic because every decision
    comes from an ordered policy list, never from the model. It is the
    composition root used by tests and local development; the HTTP layer
    injects the fully wired ``TrustEngine`` instead.
    """

    def __init__(
        self,
        permission_repository: PermissionRepository | None = None,
        default_decision: PermissionDecision = PermissionDecision.DENY,
        disabled_skills: frozenset[str] = frozenset(),
    ) -> None:
        from app.application.security.policy_registry import PolicyRegistry

        permission_checker = None
        if permission_repository is not None:
            permission_checker = permission_repository.check_permission

        super().__init__(
            PolicyRegistry(permission_checker, disabled_skills).create_policy_engine(),
            permission_repository,  # type: ignore[arg-type]
            default_decision,
        )

    def evaluate(
        self,
        tool: ToolDefinition,
        user_id: EntityId | None,
        agent_id: EntityId,
        agent_run_id: EntityId,
        arguments: dict,
    ) -> TrustEvaluation:
        return super().evaluate(tool, user_id, agent_id, agent_run_id, arguments)
