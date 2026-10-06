from sqlalchemy import and_, delete as sql_delete, select
from sqlalchemy.orm import Session

from app.domain.entities.memory import Memory
from app.domain.repositories.memory_repository import MemoryRepository
from app.domain.value_objects.entity_id import EntityId
from app.domain.value_objects.memory_type import MemoryType
from app.infrastructure.persistence.mappers.domain_mappers import memory_from_model, memory_to_model
from app.infrastructure.persistence.models import MemoryModel


class SqlAlchemyMemoryRepository(MemoryRepository):
    """Postgres-backed memory storage, scoped to an owner on every query.

    The owner filter is repeated in every method rather than applied once in a
    helper, for an uncomfortable reason: a helper is a place a future method can
    forget to call, and forgetting it here leaks another user's data. Repetition
    is the safer default for a security boundary.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, memory: Memory) -> Memory:
        if not memory.can_be_persisted:
            raise ValueError("memory marked DO_NOT_SAVE cannot be persisted")
        existing = self.session.get(MemoryModel, memory.id.value)
        if existing is None:
            self.session.add(memory_to_model(memory))
        else:
            # An update must not be able to change the owner or the agent. Both
            # are load-bearing for every subsequent read, so a caller that already
            # holds the row cannot quietly re-point it.
            existing.content = memory.content
            existing.memory_type = memory.memory_type.value
            existing.persistence = memory.persistence.value
            existing.source = memory.source.value
            existing.importance = memory.importance.value
            existing.updated_at = memory.updated_at
        self.session.commit()
        return memory_from_model(self.session.get(MemoryModel, memory.id.value))

    def get_by_id(self, memory_id: EntityId, user_id: EntityId) -> Memory | None:
        model = self.session.scalars(
            select(MemoryModel).where(
                MemoryModel.id == memory_id.value,
                MemoryModel.user_id == user_id.value,
            )
        ).first()
        return memory_from_model(model) if model else None

    def list_by_agent(
        self, agent_id: EntityId, user_id: EntityId, limit: int = 100
    ) -> list[Memory]:
        models = self.session.scalars(
            select(MemoryModel)
            .where(
                MemoryModel.agent_id == agent_id.value,
                MemoryModel.user_id == user_id.value,
            )
            .order_by(MemoryModel.created_at.desc())
            .limit(limit)
        ).all()
        return [memory_from_model(model) for model in models]

    def search(
        self,
        agent_id: EntityId,
        user_id: EntityId,
        query: str,
        limit: int = 10,
        memory_types: set[MemoryType] | None = None,
    ) -> list[Memory]:
        terms = [term for term in query.lower().split() if term]
        statement = select(MemoryModel).where(
            MemoryModel.agent_id == agent_id.value,
            MemoryModel.user_id == user_id.value,
        )
        if memory_types:
            statement = statement.where(
                MemoryModel.memory_type.in_([item.value for item in memory_types])
            )
        if terms:
            # Every term must appear (AND), not any term (OR). With OR, searching a
            # common word returns memories matching on that word alone -- which is
            # both worse recall and a wider result set than the caller asked for.
            statement = statement.where(
                and_(*(MemoryModel.content.ilike(f"%{term}%") for term in terms))
            )
        models = (
            self.session.scalars(
                statement.order_by(MemoryModel.created_at.desc()).limit(limit)
            ).all()
        )
        return [memory_from_model(model) for model in models]

    def delete(
        self, memory_id: EntityId, agent_id: EntityId, user_id: EntityId
    ) -> bool:
        model = self.session.scalars(
            select(MemoryModel).where(
                MemoryModel.id == memory_id.value,
                MemoryModel.agent_id == agent_id.value,
                MemoryModel.user_id == user_id.value,
            )
        ).first()
        if model is None:
            return False
        self.session.delete(model)
        self.session.commit()
        return True

    def delete_by_agent(self, agent_id: EntityId, user_id: EntityId) -> int:
        result = self.session.execute(
            sql_delete(MemoryModel).where(
                MemoryModel.agent_id == agent_id.value,
                MemoryModel.user_id == user_id.value,
            )
        )
        self.session.commit()
        return result.rowcount or 0