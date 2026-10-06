"""MCP integration

Revision ID: 0005_mcp
Revises: 0004_trust_engine
Create Date: 2026-09-30
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_mcp"
down_revision = "0004_trust_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create mcp_servers table
    op.create_table(
        "mcp_servers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("transport_type", sa.String(50), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("configuration", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, default=True),
        sa.Column("trust_level", sa.String(50), nullable=False, default="default"),
        sa.Column("owner_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, default="DISCONNECTED"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, onupdate=sa.func.now()),
        sa.Column("last_connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.Text(), nullable=True),
    )
    
    # Create index on owner_id for ownership queries
    op.create_index("ix_mcp_servers_owner_id", "mcp_servers", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_mcp_servers_owner_id", table_name="mcp_servers")
    op.drop_table("mcp_servers")
