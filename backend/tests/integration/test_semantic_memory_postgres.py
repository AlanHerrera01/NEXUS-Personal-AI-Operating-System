"""Real pgvector storage/ranking and owner isolation; no external model calls."""
import pytest
from sqlalchemy import delete

from app.config.settings import Settings
from app.domain.entities.agent import Agent
from app.domain.entities.memory import Memory
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.memory_type import MemoryType
from app.infrastructure.persistence.database import SessionFactory
from app.infrastructure.persistence.models import AgentModel
from app.infrastructure.persistence.repositories.agent_repository import SqlAlchemyAgentRepository
from app.infrastructure.persistence.repositories.memory_repository import SqlAlchemyMemoryRepository

pytestmark = pytest.mark.integration


class DeterministicEmbeddings:
    fingerprint = "a" * 64

    def embed(self, content):
        return [0.0, 1.0] if "hiking" in content else [1.0, 0.0]


def test_pgvector_ranks_memories_without_keyword_overlap_and_isolates_owners():
    owner, foreign_owner = EntityId.new(), EntityId.new()
    settings = Settings(_env_file=None)
    with SessionFactory() as session:
        agents = SqlAlchemyAgentRepository(session)
        agent = agents.save(Agent(name="Semantic memory validation", user_id=owner))
        other_agent = agents.save(Agent(name="Other memory validation", user_id=owner))
        try:
            repo = SqlAlchemyMemoryRepository(session, settings, DeterministicEmbeddings())
            expected = repo.save(Memory(content="Prefers Python", memory_type=MemoryType.PREFERENCE, agent_id=agent.id, user_id=owner))
            repo.save(Memory(content="Enjoys hiking", memory_type=MemoryType.SEMANTIC, agent_id=agent.id, user_id=owner))
            repo.save(Memory(content="Foreign user preference", memory_type=MemoryType.PREFERENCE, agent_id=agent.id, user_id=foreign_owner))
            repo.save(Memory(content="Other agent preference", memory_type=MemoryType.PREFERENCE, agent_id=other_agent.id, user_id=owner))
            matches = repo.search(agent.id, owner, "coding", limit=1)
            assert [memory.id for memory in matches] == [expected.id]
            matches = repo.search(agent.id, owner, "coding", limit=10)
            assert len(matches) == 2
            assert all(memory.user_id == owner and memory.agent_id == agent.id for memory in matches)
            assert [memory.id for memory in repo.search(agent.id, owner, "coding", memory_types={MemoryType.PREFERENCE})] == [expected.id]
            foreign_update = Memory(id=expected.id, content="overwrite", memory_type=MemoryType.PREFERENCE, agent_id=agent.id, user_id=foreign_owner)
            with pytest.raises(ValueError):
                repo.save(foreign_update)
            # Changing the embedding model must not compare incompatible spaces.
            repo.embeddings.fingerprint = "b" * 64
            assert repo.search(agent.id, owner, "coding") == []
        finally:
            session.rollback()
            session.execute(delete(AgentModel).where(AgentModel.id.in_([agent.id.value, other_agent.id.value])))
            session.commit()
