"""trust engine permissions and security

Revision ID: 0004_trust_engine
Revises: 0003_task_due_date
Create Date: 2026-09-30
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_trust_engine"
down_revision = "0003_task_due_date"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old permissions table
    op.drop_table("permissions")
    
    # Create new permissions table
    op.create_table(
        "permissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False, index=True),
        sa.Column("agent_id", sa.String(36), nullable=False, index=True),
        sa.Column("skill_name", sa.String(200), nullable=False),
        sa.Column("action_name", sa.String(200), nullable=False),
        sa.Column("scope", sa.String(200), nullable=False),
        sa.Column("effect", sa.String(16), nullable=False),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    
    # Create permission_requests table
    op.create_table(
        "permission_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_run_id", sa.String(36), nullable=False, index=True),
        sa.Column("tool_name", sa.String(200), nullable=False),
        sa.Column("skill_name", sa.String(200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("arguments_summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, onupdate=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    
    # Add security columns to agent_actions
    op.add_column("agent_actions", sa.Column("risk_level", sa.String(16), nullable=True))
    op.add_column("agent_actions", sa.Column("permission_decision", sa.String(16), nullable=True))
    op.add_column("agent_actions", sa.Column("policy_result", sa.String(200), nullable=True))
    op.add_column("agent_actions", sa.Column("execution_status", sa.String(200), nullable=True))
    op.add_column("agent_actions", sa.Column("error_message", sa.Text(), nullable=True))


def downgrade() -> None:
    # Remove security columns from agent_actions
    op.drop_column("agent_actions", "error_message")
    op.drop_column("agent_actions", "execution_status")
    op.drop_column("agent_actions", "policy_result")
    op.drop_column("agent_actions", "permission_decision")
    op.drop_column("agent_actions", "risk_level")
    
    # Drop permission_requests table
    op.drop_table("permission_requests")
    
    # Drop new permissions table
    op.drop_table("permissions")
    
    # Recreate old permissions table
    op.create_table(
        "permissions",
        sa.Column("skill_name", sa.String(200), nullable=False),
        sa.Column("action_name", sa.String(200), nullable=False),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.PrimaryKeyConstraint("skill_name", "action_name"),
    )
