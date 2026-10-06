import pytest

from app.application.memory.firewall import MemoryFirewall
from app.application.memory.policy import DeterministicMemoryPolicy
from app.application.memory.service import MemoryService
from app.domain.entities.agent import Agent
from app.domain.entities.memory_candidate import MemoryCandidate
from app.domain.value_objects.memory_importance import MemoryImportance
from app.domain.value_objects.memory_source import MemorySource
from app.domain.value_objects.memory_type import MemoryType
from app.infrastructure.persistence.database import SessionFactory
from app.infrastructure.persistence.repositories.agent_repository import SqlAlchemyAgentRepository
from app.infrastructure.persistence.repositories.memory_repository import SqlAlchemyMemoryRepository

pytestmark = pytest.mark.integration


def test_memory_persists_searches_isolates_and_deletes() -> None:
    session = SessionFactory()
    try:
        agent_repository = SqlAlchemyAgentRepository(session)
        agent_a = agent_repository.save(Agent(name="Memory integration A"))
        agent_b = agent_repository.save(Agent(name="Memory integration B"))
        service = MemoryService(
            SqlAlchemyMemoryRepository(session),
            DeterministicMemoryPolicy(),
            MemoryFirewall(),
        )

        result = service.save_memory(
            MemoryCandidate(
                agent_id=agent_a.id,
                content="The user prefers Docker for local development.",
                memory_type=MemoryType.PREFERENCE,
                source=MemorySource.USER_EXPLICIT,
                importance=MemoryImportance.HIGH,
            )
        )

        assert result.memory is not None
        assert len(service.list_memories(agent_a.id)) == 1
        assert service.list_memories(agent_b.id) == []
        assert len(service.retrieve_memories(agent_a.id, "Docker")) == 1
        assert service.retrieve_memories(agent_b.id, "Docker") == []
        assert service.delete_memory(result.memory.id, agent_b.id) is False
        assert service.delete_memory(result.memory.id, agent_a.id) is True
        assert service.list_memories(agent_a.id) == []
    finally:
        session.rollback()
        session.close()
