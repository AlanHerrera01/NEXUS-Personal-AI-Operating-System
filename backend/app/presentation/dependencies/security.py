from fastapi import Depends
from sqlalchemy.orm import Session

from app.application.permissions.permission_service import PermissionService
from app.application.security.approval_service import ApprovalService
from app.application.security.audit import SecurityAuditLog
from app.application.security.policy_engine import PolicyEngine
from app.application.security.policy_registry import PolicyRegistry
from app.application.security.trust_engine import TrustEngine
from app.config.settings import get_settings
from app.domain.repositories.permission_repository import PermissionRepository
from app.domain.value_objects.permission_decision import PermissionDecision
from app.infrastructure.persistence.repositories.permission_repository import SqlPermissionRepository
from app.infrastructure.persistence.repositories.permission_request_repository import (
    SqlPermissionRequestRepository,
)
from app.presentation.dependencies.persistence import session_dependency


def get_permission_repository(session: Session = Depends(session_dependency)) -> PermissionRepository:
    return SqlPermissionRepository(session)


def get_permission_request_repository(
    session: Session = Depends(session_dependency),
) -> SqlPermissionRequestRepository:
    return SqlPermissionRequestRepository(session)


def get_permission_service(
    permission_repository: PermissionRepository = Depends(get_permission_repository),
) -> PermissionService:
    return PermissionService(permission_repository)


def get_approval_service(
    permission_request_repository: SqlPermissionRequestRepository = Depends(
        get_permission_request_repository
    ),
) -> ApprovalService:
    return ApprovalService(
        permission_request_repository,
        request_ttl_seconds=get_settings().permission_request_ttl_seconds,
    )


def get_policy_registry(
    permission_repository: PermissionRepository = Depends(get_permission_repository),
) -> PolicyRegistry:
    settings = get_settings()
    return PolicyRegistry(
        # The repository is now actually connected. It was passed as None, which
        # meant the permission policy was never constructed and no grant, deny or
        # expiry written through the permissions API influenced a single decision.
        permission_resolver=permission_repository.resolve,
        disabled_skills=frozenset(
            name.strip() for name in settings.disabled_skills.split(",") if name.strip()
        ),
    )


def get_policy_engine(policy_registry: PolicyRegistry = Depends(get_policy_registry)) -> PolicyEngine:
    return policy_registry.create_policy_engine()


def get_trust_engine(
    policy_engine: PolicyEngine = Depends(get_policy_engine),
    permission_repository: PermissionRepository = Depends(get_permission_repository),
) -> TrustEngine:
    return TrustEngine(
        policy_engine,
        permission_repository,
        default_decision=PermissionDecision(get_settings().trust_default_decision),
    )


def get_security_audit() -> SecurityAuditLog:
    """The process-wide audit sink.

    One ring per process so the trail is queryable across requests rather than
    per-request. In-memory and therefore bounded and lossy on restart: an
    operational aid, not a compliance store.
    """
    global _security_audit_log
    if _security_audit_log is None:
        _security_audit_log = SecurityAuditLog(
            capacity=get_settings().security_audit_capacity
        )
    return _security_audit_log


# Built on first use rather than at import. Reading settings at import time made
# a misconfigured environment fail while merely importing a module, which points
# at the import rather than at the setting.
_security_audit_log: SecurityAuditLog | None = None
