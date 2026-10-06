"""add task due date

Revision ID: 0003_task_due_date
Revises: 0002_memory
Create Date: 2026-09-30
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_task_due_date"
down_revision = "0002_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("due_date", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "due_date")
