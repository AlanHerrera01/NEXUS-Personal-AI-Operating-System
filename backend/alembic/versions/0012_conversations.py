"""conversations system

Groups multiple agent runs into a single conversation thread. Each conversation
can have multiple related runs that share context.

Revision ID: 0012_conversations
Revises: 0011_agent_run_outcome
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_conversations"
down_revision = "0011_agent_run_outcome"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create conversations table
    op.create_table(
        "conversations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_conversations_user_id"), "conversations", ["user_id"], unique=False)
    op.create_index(op.f("ix_conversations_updated_at"), "conversations", ["updated_at"], unique=False)

    # Add conversation_id to agent_runs
    op.add_column(
        "agent_runs",
        sa.Column("conversation_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_runs_conversation_id_conversations",
        "agent_runs",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_agent_runs_conversation_id"), "agent_runs", ["conversation_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_runs_conversation_id"), table_name="agent_runs")
    op.drop_constraint("fk_agent_runs_conversation_id_conversations", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "conversation_id")

    op.drop_index(op.f("ix_conversations_updated_at"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_user_id"), table_name="conversations")
    op.drop_table("conversations")
