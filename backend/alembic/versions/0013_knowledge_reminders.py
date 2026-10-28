"""knowledge chunks and time-based reminders

Both tables are owner-scoped. ``agent_id`` mirrors tasks and calendar events:
nullable and ``ON DELETE SET NULL`` so deleting an agent does not delete the
user's data. ``knowledge_chunks`` has no document table because replacement is
done as delete-and-insert for one source, which keeps re-ingest atomic without a
second lifecycle to maintain.

Revision ID: 0013_knowledge_reminders
Revises: 0012_conversations
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_knowledge_reminders"
down_revision = "0012_conversations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(length=1000), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("document_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_knowledge_chunks_agent_user",
        "knowledge_chunks",
        ["agent_id", "user_id"],
    )
    op.create_index("ix_knowledge_chunks_source", "knowledge_chunks", ["source"])

    op.create_table(
        "reminders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("remind_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="PENDING"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reminders_agent_user", "reminders", ["agent_id", "user_id"])
    op.create_index("ix_reminders_remind_at", "reminders", ["remind_at"])


def downgrade() -> None:
    op.drop_index("ix_reminders_remind_at", table_name="reminders")
    op.drop_index("ix_reminders_agent_user", table_name="reminders")
    op.drop_table("reminders")
    op.drop_index("ix_knowledge_chunks_source", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_agent_user", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
