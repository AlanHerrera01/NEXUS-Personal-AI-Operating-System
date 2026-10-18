"""Runtime settings overrides

One row holding the operator-tunable knobs changed from the UI: the model id,
the generation parameters, the request timeout and a notification preference.
Every column is nullable, and ``NULL`` means "no override -- inherit the process
environment" (see ``app/domain/entities/runtime_settings.py``). That is why the
columns are not ``NOT NULL`` with defaults: a baked-in default would make an
override indistinguishable from an inherited value, and the panel could not tell
the operator which one they are looking at.

The table is intentionally singleton: ``id`` is the constant ``'global'``. There
is one effective configuration per deployment, so a second row would be a bug
rather than a second profile.

Revision ID: 0009_runtime_settings
Revises: 0008_ownership
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_runtime_settings"
down_revision = "0008_ownership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runtime_settings",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("request_timeout_seconds", sa.Float(), nullable=True),
        sa.Column("notifications_enabled", sa.Boolean(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("runtime_settings")
