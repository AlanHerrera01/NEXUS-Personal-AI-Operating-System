"""Dependency providers for the dashboard overview read model.

These are thin wrappers around the request-scoped session, named individually so
the overview route's data sources can be substituted in tests without a database.
They deliberately do not reuse the always-on providers: an override here should
not silently rewrite how a scheduled job resolves its repositories.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.infrastructure.persistence.repositories.agent_repository import (
    SqlAlchemyAgentRepository,
)
from app.infrastructure.persistence.repositories.agent_run_repository import (
    SqlAlchemyAgentRunRepository,
)
from app.infrastructure.persistence.repositories.permission_repository import (
    SqlPermissionRepository,
)
from app.infrastructure.persistence.repositories.permission_request_repository import (
    SqlPermissionRequestRepository,
)
from app.presentation.dependencies.persistence import session_dependency


def get_overview_agent_run_repository(
    session: Session = Depends(session_dependency),
) -> SqlAlchemyAgentRunRepository:
    return SqlAlchemyAgentRunRepository(session)


def get_overview_agent_repository(
    session: Session = Depends(session_dependency),
) -> SqlAlchemyAgentRepository:
    return SqlAlchemyAgentRepository(session)


def get_overview_permission_repository(
    session: Session = Depends(session_dependency),
) -> SqlPermissionRepository:
    return SqlPermissionRepository(session)


def get_overview_permission_request_repository(
    session: Session = Depends(session_dependency),
) -> SqlPermissionRequestRepository:
    return SqlPermissionRequestRepository(session)
