from dataclasses import dataclass

from app.application.knowledge.errors import InvalidKnowledgeError
from app.domain.entities.knowledge_chunk import KnowledgeChunk
from app.domain.repositories.knowledge_repository import KnowledgeRepository
from app.domain.value_objects.entity_id import EntityId
from app.infrastructure.documents.chunking import chunk_text

MAX_SOURCE_LENGTH = 1_000
MAX_TITLE_LENGTH = 300
MAX_DOCUMENT_CHARS = 200_000
MIN_CHUNK_CHARS = 200
MAX_CHUNK_CHARS = 4_000


@dataclass(frozen=True, slots=True)
class IngestKnowledgeResult:
    source: str
    title: str
    chunks: int
    characters: int
    created: bool
    document_hash: str


@dataclass
class IngestKnowledgeUseCase:
    repository: KnowledgeRepository

    def execute(
        self,
        *,
        agent_id: EntityId,
        user_id: EntityId | None,
        source: str,
        title: str,
        text: str,
        max_document_chars: int = MAX_DOCUMENT_CHARS,
        chunk_chars: int = 1_200,
        chunk_overlap: int = 150,
    ) -> IngestKnowledgeResult:
        source = source.strip()
        title = title.strip()
        text = text.strip()
        if not source:
            raise InvalidKnowledgeError("source must not be empty")
        if len(source) > MAX_SOURCE_LENGTH:
            raise InvalidKnowledgeError(
                f"source must be at most {MAX_SOURCE_LENGTH} characters"
            )
        if not title:
            raise InvalidKnowledgeError("title must not be empty")
        if len(title) > MAX_TITLE_LENGTH:
            raise InvalidKnowledgeError(
                f"title must be at most {MAX_TITLE_LENGTH} characters"
            )
        if not text:
            raise InvalidKnowledgeError("the document contains no text")
        if len(text) > max_document_chars:
            text = text[:max_document_chars]

        chunk_chars = max(MIN_CHUNK_CHARS, min(chunk_chars, MAX_CHUNK_CHARS))
        chunk_overlap = max(0, min(chunk_overlap, chunk_chars // 2))

        import hashlib

        document_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        existing_hash = self.repository.document_hash(agent_id, user_id, source)
        if existing_hash == document_hash:
            return IngestKnowledgeResult(
                source=source,
                title=title,
                chunks=self.repository.count_document(agent_id, user_id, source),
                characters=len(text),
                created=False,
                document_hash=document_hash,
            )

        pieces = chunk_text(text, max_chars=chunk_chars, overlap=chunk_overlap)
        if not pieces:
            raise InvalidKnowledgeError("the document contains no text")

        chunks = [
            KnowledgeChunk(
                source=source,
                title=title,
                content=piece,
                chunk_index=index,
                document_hash=document_hash,
                agent_id=agent_id,
                user_id=user_id,
            )
            for index, piece in enumerate(pieces)
        ]
        count = self.repository.replace_document(
            agent_id=agent_id,
            user_id=user_id,
            source=source,
            chunks=chunks,
        )
        return IngestKnowledgeResult(
            source=source,
            title=title,
            chunks=count,
            characters=len(text),
            created=True,
            document_hash=document_hash,
        )
