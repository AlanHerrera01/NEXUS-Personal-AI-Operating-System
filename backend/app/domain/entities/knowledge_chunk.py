from dataclasses import dataclass, field
from datetime import datetime

from app.domain.entities._common import require_text, utc_now
from app.domain.value_objects.entity_id import EntityId


@dataclass
class KnowledgeChunk:
    """One retrievable slice of a local knowledge document.

    The source and document hash are stored on every chunk rather than in a
    separate documents table. That keeps replacement atomic: a re-ingest deletes
    the old rows for a source and writes the new ones in the same transaction,
    with no window in which the document exists but is not searchable.
    """

    source: str
    title: str
    content: str
    chunk_index: int
    document_hash: str
    agent_id: EntityId | None = None
    user_id: EntityId | None = None
    id: EntityId = field(default_factory=EntityId.new)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        require_text(self.source, "source")
        require_text(self.title, "title")
        require_text(self.content, "content")
        if self.chunk_index < 0:
            raise ValueError("chunk_index must not be negative")
        if len(self.document_hash) != 64:
            raise ValueError("document_hash must be a SHA-256 hex digest")
