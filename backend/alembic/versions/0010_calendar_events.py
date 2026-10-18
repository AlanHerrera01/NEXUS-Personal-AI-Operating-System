"""the agent's own calendar

Events live in NEXUS rather than in a provider: the calendar tools write here and
read here, so the table carries no external id, no provider URL and no sync
state -- fields it would otherwise hold empty forever, and which a later reader
would try to fill by inventing a sync that does not exist.

``agent_id`` mirrors ``tasks``: nullable and ``ON DELETE SET NULL``, so deleting
an agent loses the owner of an appointment but not the appointment itself.

``start_at`` is indexed because both tools filter and sort on it.

Revision ID: 0010_calendar_events
Revises: 0009_runtime_settings
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_calendar_events"
down_revision = "0009_runtime_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calendar_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("location", sa.String(length=300), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
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
    op.create_index("ix_calendar_events_agent_id", "calendar_events", ["agent_id"])
    op.create_index("ix_calendar_events_start_at", "calendar_events", ["start_at"])


def downgrade() -> None:
    op.drop_index("ix_calendar_events_start_at", table_name="calendar_events")
    op.drop_index("ix_calendar_events_agent_id", table_name="calendar_events")
    op.drop_table("calendar_events")
