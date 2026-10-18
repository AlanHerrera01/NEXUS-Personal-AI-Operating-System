"""Dependency providers for the activity read model.

Thin wrappers around the request-scoped session, named individually so the
activity route's data sources can be substituted in tests without a database --
the same reason the overview providers exist. They are kept separate from the
overview providers so overriding one read model cannot silently rewrite the
other.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.infrastructure.persistence.repositories.agent_action_repository import (
    SqlAlchemyAgentActionRepository,
)
from app.infrastructure.persistence.repositories.agent_run_repository import (
    SqlAlchemyAgentRunRepository,
)
from app.infrastructure.persistence.repositories.memory_repository import (
    SqlAlchemyMemoryRepository,
)
from app.infrastructure.persistence.repositories.permission_request_repository import (
    SqlPermissionRequestRepository,
)
from app.presentation.dependencies.persistence import session_dependency


def get_activity_agent_run_repository(
    session: Session = Depends(session_dependency),
) -> SqlAlchemyAgentRunRepository:
    return SqlAlchemyAgentRunRepository(session)


def get_activity_action_repository(
    session: Session = Depends(session_dependency),
) -> SqlAlchemyAgentActionRepository:
    return SqlAlchemyAgentActionRepository(session)


def get_activity_permission_request_repository(
    session: Session = Depends(session_dependency),
) -> SqlPermissionRequestRepository:
    return SqlPermissionRequestRepository(session)


def get_activity_memory_repository(
    session: Session = Depends(session_dependency),
) -> SqlAlchemyMemoryRepository:
    return SqlAlchemyMemoryRepository(session)
