from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.domain.entities.conversation import Conversation
from app.domain.ports.conversation_repository import ConversationRepositoryPort
from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.persistence.models import ConversationModel


class SqlAlchemyConversationRepository(ConversationRepositoryPort):
    def __init__(self, session: Session) -> None:
        self.session = session

    async def save(self, conversation: Conversation) -> Conversation:
        existing = self.session.get(ConversationModel, conversation.id.value)
        if existing is None:
            model = ConversationModel(
                id=conversation.id.value,
                title=conversation.title,
                user_id=conversation.user_id.value if conversation.user_id else None,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
            )
            self.session.add(model)
        else:
            existing.title = conversation.title
            existing.updated_at = conversation.updated_at
        self.session.commit()
        return self._model_to_entity(self.session.get(ConversationModel, conversation.id.value))

    async def get_by_id(self, conversation_id: EntityId) -> Conversation | None:
        model = self.session.get(ConversationModel, conversation_id.value)
        return self._model_to_entity(model) if model else None

    async def list_by_user(self, user_id: EntityId) -> list[Conversation]:
        models = self.session.scalars(
            select(ConversationModel)
            .where(ConversationModel.user_id == user_id.value)
            .order_by(ConversationModel.updated_at.desc())
        ).all()
        return [self._model_to_entity(model) for model in models]

    async def delete(self, conversation_id: EntityId) -> None:
        model = self.session.get(ConversationModel, conversation_id.value)
        if model:
            self.session.delete(model)
            self.session.commit()

    def _model_to_entity(self, model: ConversationModel | None) -> Conversation | None:
        if model is None:
            return None
        return Conversation(
            id=EntityId(model.id),
            title=model.title,
            user_id=EntityId(model.user_id) if model.user_id else None,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
