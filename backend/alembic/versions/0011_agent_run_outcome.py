"""what a run said when it stopped

A run stored its status but not its words. The closing response (or the question
it parked on) lived only in the HTTP response of the call that produced it, so a
run reopened later -- a recent run selected from the sidebar -- had nothing to
show but its plan. These two columns keep the exchange with the run.

Both are nullable: a run that is still moving has said neither yet, and a run
created before this migration simply has no recorded outcome.

Revision ID: 0011_agent_run_outcome
Revises: 0010_calendar_events
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_agent_run_outcome"
down_revision = "0010_calendar_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("response", sa.Text(), nullable=True))
    op.add_column("agent_runs", sa.Column("question", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_runs", "question")
    op.drop_column("agent_runs", "response")
