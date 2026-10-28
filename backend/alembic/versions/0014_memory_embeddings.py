"""Real pgvector memory embeddings, nullable for existing keyword-only memories."""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "0014_memory_embeddings"
down_revision = "0013_knowledge_reminders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("memories", sa.Column("embedding", Vector(), nullable=True))
    op.add_column("memories", sa.Column("embedding_model", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("memories", "embedding_model")
    op.drop_column("memories", "embedding")
    # The extension may also be used by other applications; leave it installed.
