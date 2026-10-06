"""Runtime sessions

Revision ID: 0006_runtime_sessions
Revises: 0005_mcp
Create Date: 2026-09-30
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_runtime_sessions"
down_revision = "0005_mcp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "agent_run_id",
            sa.Uuid(),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(20), nullable=False, server_default="LOCAL"),
        sa.Column("state", sa.String(20), nullable=False, server_default="CREATED"),
        sa.Column("sandbox_id", sa.String(200), nullable=True),
        sa.Column("workspace_path", sa.String(1024), nullable=False),
        sa.Column("policy", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.create_index("ix_runtime_sessions_agent_run_id", "runtime_sessions", ["agent_run_id"])
    op.create_index("ix_runtime_sessions_user_id", "runtime_sessions", ["user_id"])
    op.create_index("ix_runtime_sessions_state", "runtime_sessions", ["state"])

    # Marks a permission request as spent, so one human approval cannot be
    # replayed to authorize a second execution.
    op.add_column(
        "permission_requests",
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("permission_requests", "consumed_at")
    op.drop_index("ix_runtime_sessions_state", table_name="runtime_sessions")
    op.drop_index("ix_runtime_sessions_user_id", table_name="runtime_sessions")
    op.drop_index("ix_runtime_sessions_agent_run_id", table_name="runtime_sessions")
    op.drop_table("runtime_sessions")