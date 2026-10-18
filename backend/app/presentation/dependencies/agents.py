"""Dependency providers for the agent registry.

Named individually for the same reason the overview and activity providers are:
the route's data source can be substituted in tests without a database.
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from app.infrastructure.persistence.repositories.agent_repository import (
    SqlAlchemyAgentRepository,
)
from app.presentation.dependencies.persistence import session_dependency


def get_agent_repository(
    session: Session = Depends(session_dependency),
) -> SqlAlchemyAgentRepository:
    return SqlAlchemyAgentRepository(session)
