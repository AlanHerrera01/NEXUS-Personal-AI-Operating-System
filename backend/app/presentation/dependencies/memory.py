from fastapi import Depends
from sqlalchemy.orm import Session

from app.application.memory.firewall import MemoryFirewall
from app.application.memory.policy import DeterministicMemoryPolicy
from app.application.memory.service import MemoryService
from app.infrastructure.persistence.repositories.memory_repository import SqlAlchemyMemoryRepository
from app.presentation.dependencies.persistence import session_dependency


def memory_service_dependency(session: Session = Depends(session_dependency)) -> MemoryService:
    return MemoryService(
        repository=SqlAlchemyMemoryRepository(session),
        policy=DeterministicMemoryPolicy(),
        firewall=MemoryFirewall(),
    )
