"""Always-On: scheduled jobs, executions, trigger events, proactive rules.

The unique constraint on ``job_executions.idempotency_key`` is the load-bearing
part of this migration. It is what lets N worker processes find the same
occurrence due and still dispatch it exactly once: every worker derives the same
key from ``(job, occurrence)``, so the second insert fails and that worker backs
off. Application-level locking would not survive a second process, and an
``INSERT ... ON CONFLICT DO NOTHING`` without the constraint underneath it is
just a hopeful write.

``trigger_events.idempotency_key`` does the same job one level up, for providers
that retry webhook deliveries.

Indexes are chosen from the queries that actually exist, not from the columns
that happen to be filtered on:

* ``ix_scheduled_jobs_due (status, next_run_at)`` -- the dispatcher's hot path,
  "active clock jobs that are due", which is otherwise a sequential scan.
* ``ix_job_executions_status`` -- the recovery sweep only ever asks "give me
  RUNNING", and a partial-style leading-column index serves that directly.
* ``ix_trigger_events_user_received (user_id, received_at)`` -- the rate
  limiter counts a user's events in the last minute on every single ingest.
* ``ix_proactive_rules_user_enabled (user_id, enabled)`` -- every evaluation
  pass asks for exactly this.

Revision ID: 0007_always_on
Revises: 0006_runtime_sessions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_always_on"
down_revision = "0006_runtime_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduled_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=4000), nullable=False, server_default=""),
        sa.Column("trigger_type", sa.String(length=20), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
        sa.Column("cron_expression", sa.String(length=200), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], ondelete="CASCADE", name="fk_scheduled_jobs_agent_id"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scheduled_jobs_user_id", "scheduled_jobs", ["user_id"])
    op.create_index("ix_scheduled_jobs_agent_id", "scheduled_jobs", ["agent_id"])
    op.create_index(
        "ix_scheduled_jobs_due", "scheduled_jobs", ["status", "next_run_at"]
    )

    op.create_table(
        "trigger_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        # Unique: a retried webhook delivery must not become a second dispatch.
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_trigger_events_idempotency_key"),
    )
    op.create_index("ix_trigger_events_user_id", "trigger_events", ["user_id"])
    op.create_index("ix_trigger_events_event_type", "trigger_events", ["event_type"])
    op.create_index(
        "ix_trigger_events_user_received",
        "trigger_events",
        ["user_id", "received_at"],
    )

    op.create_table(
        "job_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scheduled_job_id", sa.Uuid(), nullable=False),
        # SET NULL, not CASCADE: deleting an agent run must not erase the record
        # that a scheduled job fired, which is exactly the history a user needs
        # when asking "did it run?".
        sa.Column("agent_run_id", sa.Uuid(), nullable=True),
        sa.Column("trigger_event_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        # Unique: the mechanism that collapses at-least-once dispatch to
        # effectively-once across any number of worker processes.
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="QUEUED"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("result_summary", sa.String(length=2000), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id"],
            ["agent_runs.id"],
            ondelete="SET NULL",
            name="fk_job_executions_agent_run_id",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_event_id"],
            ["trigger_events.id"],
            ondelete="SET NULL",
            name="fk_job_executions_trigger_event_id",
        ),
        sa.ForeignKeyConstraint(
            ["scheduled_job_id"],
            ["scheduled_jobs.id"],
            ondelete="CASCADE",
            name="fk_job_executions_scheduled_job_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_job_executions_idempotency_key"
        ),
    )
    op.create_index("ix_job_executions_job_id", "job_executions", ["scheduled_job_id"])
    op.create_index("ix_job_executions_agent_run_id", "job_executions", ["agent_run_id"])
    op.create_index("ix_job_executions_user_id", "job_executions", ["user_id"])
    op.create_index("ix_job_executions_status", "job_executions", ["status"])
    op.create_index(
        "ix_job_executions_user_status", "job_executions", ["user_id", "status"]
    )

    op.create_table(
        "proactive_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("condition", sa.JSON(), nullable=False),
        sa.Column("action", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "cooldown_seconds", sa.Integer(), nullable=False, server_default="3600"
        ),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger_count", sa.Integer(), nullable=False, server_default="0"),
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
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], ondelete="CASCADE", name="fk_proactive_rules_agent_id"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_proactive_rules_user_id", "proactive_rules", ["user_id"])
    op.create_index(
        "ix_proactive_rules_user_enabled", "proactive_rules", ["user_id", "enabled"]
    )


def downgrade() -> None:
    op.drop_index("ix_proactive_rules_user_enabled", table_name="proactive_rules")
    op.drop_index("ix_proactive_rules_user_id", table_name="proactive_rules")
    op.drop_table("proactive_rules")

    op.drop_index("ix_job_executions_user_status", table_name="job_executions")
    op.drop_index("ix_job_executions_status", table_name="job_executions")
    op.drop_index("ix_job_executions_user_id", table_name="job_executions")
    op.drop_index("ix_job_executions_agent_run_id", table_name="job_executions")
    op.drop_index("ix_job_executions_job_id", table_name="job_executions")
    op.drop_table("job_executions")

    op.drop_index("ix_trigger_events_user_received", table_name="trigger_events")
    op.drop_index("ix_trigger_events_event_type", table_name="trigger_events")
    op.drop_index("ix_trigger_events_user_id", table_name="trigger_events")
    op.drop_table("trigger_events")

    op.drop_index("ix_scheduled_jobs_due", table_name="scheduled_jobs")
    op.drop_index("ix_scheduled_jobs_agent_id", table_name="scheduled_jobs")
    op.drop_index("ix_scheduled_jobs_user_id", table_name="scheduled_jobs")
    op.drop_table("scheduled_jobs")