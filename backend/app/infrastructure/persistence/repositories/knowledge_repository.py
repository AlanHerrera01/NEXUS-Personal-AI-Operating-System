from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.domain.entities.knowledge_chunk import KnowledgeChunk
from app.domain.repositories.knowledge_repository import KnowledgeRepository
from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.persistence.mappers.domain_mappers import (
    knowledge_chunk_from_model,
    knowledge_chunk_to_model,
)
from app.infrastructure.persistence.models import KnowledgeChunkModel


class SqlAlchemyKnowledgeRepository(KnowledgeRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def document_hash(
        self, agent_id: EntityId, user_id: EntityId | None, source: str
    ) -> str | None:
        model = self.session.scalars(
            self._scope(
                select(KnowledgeChunkModel).where(KnowledgeChunkModel.source == source),
                agent_id,
                user_id,
            ).limit(1)
        ).first()
        return model.document_hash if model else None

    def count_document(
        self, agent_id: EntityId, user_id: EntityId | None, source: str
    ) -> int:
        statement = self._scope(
            select(func.count())
            .select_from(KnowledgeChunkModel)
            .where(KnowledgeChunkModel.source == source),
            agent_id,
            user_id,
        )
        return int(self.session.scalar(statement) or 0)

    def replace_document(
        self,
        *,
        agent_id: EntityId,
        user_id: EntityId | None,
        source: str,
        chunks: list[KnowledgeChunk],
    ) -> int:
        statement = self._scope(
            delete(KnowledgeChunkModel).where(KnowledgeChunkModel.source == source),
            agent_id,
            user_id,
        )
        self.session.execute(statement)
        if chunks:
            self.session.add_all([knowledge_chunk_to_model(chunk) for chunk in chunks])
        self.session.commit()
        return len(chunks)

    def search(
        self,
        *,
        agent_id: EntityId,
        user_id: EntityId | None,
        query: str,
        candidate_limit: int,
    ) -> list[KnowledgeChunk]:
        terms = [term for term in query.lower().split() if term]
        if not terms:
            return []
        statement = self._scope(select(KnowledgeChunkModel), agent_id, user_id)
        for term in terms:
            pattern = f"%{_escape_like(term)}%"
            statement = statement.where(
                or_(
                    KnowledgeChunkModel.content.ilike(pattern, escape="\\"),
                    KnowledgeChunkModel.title.ilike(pattern, escape="\\"),
                )
            )
        models = self.session.scalars(
            statement.order_by(KnowledgeChunkModel.created_at.desc()).limit(
                max(1, candidate_limit)
            )
        ).all()
        return [knowledge_chunk_from_model(model) for model in models]

    @staticmethod
    def _scope(statement, agent_id: EntityId, user_id: EntityId | None):
        statement = statement.where(KnowledgeChunkModel.agent_id == agent_id.value)
        if user_id is None:
            return statement.where(KnowledgeChunkModel.user_id.is_(None))
        return statement.where(KnowledgeChunkModel.user_id == user_id.value)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
