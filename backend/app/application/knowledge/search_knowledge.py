from dataclasses import dataclass

from app.application.knowledge.errors import InvalidKnowledgeError
from app.domain.entities.knowledge_chunk import KnowledgeChunk
from app.domain.repositories.knowledge_repository import KnowledgeRepository
from app.domain.value_objects.entity_id import EntityId

MAX_QUERY_LENGTH = 500
MAX_LIMIT = 20


@dataclass(frozen=True, slots=True)
class KnowledgeMatch:
    chunk: KnowledgeChunk
    score: float


@dataclass
class SearchKnowledgeUseCase:
    repository: KnowledgeRepository

    def execute(
        self,
        *,
        agent_id: EntityId,
        user_id: EntityId | None,
        query: str,
        limit: int = 5,
    ) -> list[KnowledgeMatch]:
        query = query.strip()
        if not query:
            raise InvalidKnowledgeError("query must not be empty")
        if len(query) > MAX_QUERY_LENGTH:
            raise InvalidKnowledgeError(
                f"query must be at most {MAX_QUERY_LENGTH} characters"
            )
        if limit < 1 or limit > MAX_LIMIT:
            raise InvalidKnowledgeError(f"limit must be between 1 and {MAX_LIMIT}")

        terms = [term for term in query.lower().split() if term]
        candidates = self.repository.search(
            agent_id=agent_id,
            user_id=user_id,
            query=query,
            candidate_limit=min(limit * 5, 100),
        )
        matches: list[KnowledgeMatch] = []
        for chunk in candidates:
            haystack = chunk.content.lower()
            title = chunk.title.lower()
            score = sum(haystack.count(term) + 3 * title.count(term) for term in terms)
            if score <= 0:
                continue
            matches.append(KnowledgeMatch(chunk=chunk, score=float(score)))

        matches.sort(
            key=lambda match: (match.score, match.chunk.created_at.timestamp()),
            reverse=True,
        )
        return matches[:limit]
