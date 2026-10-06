"""add memory ownership and policy metadata

Revision ID: 0002_memory
Revises: 0001_initial
Create Date: 2026-09-30
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_memory"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("memories", sa.Column("agent_id", sa.Uuid(), nullable=True))
    op.add_column("memories", sa.Column("source", sa.String(length=32), server_default="SYSTEM", nullable=False))
    op.add_column("memories", sa.Column("importance", sa.String(length=16), server_default="MEDIUM", nullable=False))
    op.create_foreign_key(
        "fk_memories_agent_id_agents",
        "memories",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_memories_agent_id", "memories", ["agent_id"])
    op.create_index("ix_memories_agent_type", "memories", ["agent_id", "memory_type"])


def downgrade() -> None:
    op.drop_index("ix_memories_agent_type", table_name="memories")
    op.drop_index("ix_memories_agent_id", table_name="memories")
    op.drop_constraint("fk_memories_agent_id_agents", "memories", type_="foreignkey")
    op.drop_column("memories", "importance")
    op.drop_column("memories", "source")
    op.drop_column("memories", "agent_id")
