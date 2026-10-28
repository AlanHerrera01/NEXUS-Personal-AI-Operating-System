from abc import ABC, abstractmethod

from app.domain.entities.knowledge_chunk import KnowledgeChunk
from app.domain.value_objects.entity_id import EntityId


class KnowledgeRepository(ABC):
    """Persistence port for the local, chunked knowledge base.

    Every method takes the owner. A search that does not know whose knowledge
    it is searching is a cross-user read waiting to happen, so the port does not
    offer one.
    """

    @abstractmethod
    def document_hash(
        self, agent_id: EntityId, user_id: EntityId | None, source: str
    ) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def count_document(
        self, agent_id: EntityId, user_id: EntityId | None, source: str
    ) -> int:
        raise NotImplementedError

    @abstractmethod
    def replace_document(
        self,
        *,
        agent_id: EntityId,
        user_id: EntityId | None,
        source: str,
        chunks: list[KnowledgeChunk],
    ) -> int:
        """Delete this source's old chunks and write ``chunks`` atomically."""
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        *,
        agent_id: EntityId,
        user_id: EntityId | None,
        query: str,
        candidate_limit: int,
    ) -> list[KnowledgeChunk]:
        """Chunks matching every query term, best-effort ordered by recency."""
        raise NotImplementedError
