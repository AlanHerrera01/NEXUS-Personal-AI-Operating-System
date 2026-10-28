from abc import ABC, abstractmethod

from app.domain.entities.conversation import Conversation
from app.domain.value_objects.entity_id import EntityId


class ConversationRepositoryPort(ABC):
    """Port for conversation persistence operations."""

    @abstractmethod
    async def save(self, conversation: Conversation) -> Conversation:
        """Save a conversation (create or update)."""
        pass

    @abstractmethod
    async def get_by_id(self, conversation_id: EntityId) -> Conversation | None:
        """Get a conversation by its ID."""
        pass

    @abstractmethod
    async def list_by_user(self, user_id: EntityId) -> list[Conversation]:
        """List all conversations for a given user, ordered by updated_at desc."""
        pass

    @abstractmethod
    async def delete(self, conversation_id: EntityId) -> None:
        """Delete a conversation by its ID."""
        pass
