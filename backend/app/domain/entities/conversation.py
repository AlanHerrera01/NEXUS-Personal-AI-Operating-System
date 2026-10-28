from dataclasses import dataclass, field
from datetime import datetime

from app.domain.entities._common import require_text, utc_now
from app.domain.value_objects.entity_id import EntityId


@dataclass
class Conversation:
    """A conversation groups multiple agent runs into a single thread.

    Each conversation represents a session where a user can send multiple
    messages (agent runs) that are related to each other and share context.
    """
    title: str
    id: EntityId = field(default_factory=EntityId.new)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    #: Owner of the conversation. Separate from the agent's owner.
    user_id: EntityId | None = None

    def __post_init__(self) -> None:
        require_text(self.title, "title")

    def update_timestamp(self) -> None:
        """Update the updated_at timestamp to the current time."""
        self.updated_at = utc_now()
