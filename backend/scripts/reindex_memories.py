"""Explicitly embed the authenticated local operator's existing memories.

Run from backend: python -m scripts.reindex_memories
This sends memory contents to the configured embedding provider and may cost money.
"""
from sqlalchemy import or_, select

from app.config.settings import get_settings
from app.infrastructure.llm.embeddings import EmbeddingProvider
from app.infrastructure.persistence.database import SessionFactory
from app.infrastructure.persistence.models import MemoryModel
from app.presentation.dependencies.identity import LOCAL_USER_ID


def main() -> None:
    settings = get_settings()
    if settings.memory_search_mode != "semantic":
        raise SystemExit("Set MEMORY_SEARCH_MODE=semantic and configure the embedding provider first.")
    provider = EmbeddingProvider(settings)
    count = 0
    with SessionFactory() as session:
        while True:
            rows = session.scalars(select(MemoryModel).where(
                MemoryModel.user_id == LOCAL_USER_ID,
                or_(MemoryModel.embedding.is_(None), MemoryModel.embedding_model.is_(None), MemoryModel.embedding_model != provider.fingerprint),
            ).order_by(MemoryModel.id).limit(50)).all()
            if not rows:
                break
            for row in rows:
                row.embedding = provider.embed(row.content)
                row.embedding_model = provider.fingerprint
            session.commit()
            count += len(rows)
            print(f"Indexed {count} memories.")


if __name__ == "__main__":
    main()
