"""Ownership: agents, agent runs, memories and permission requests.

Every security check NEXUS makes about "is this caller allowed to see this" is
ultimately a comparison against an owner column. Before this revision there was
nothing to compare: ``memories`` were keyed only by ``agent_id``, ``agents`` and
``agent_runs`` carried no owner at all, and a permission request remembered that
*somebody* was asked but never who. The application layer filtered by
``agent_id``, which the caller supplied. Any caller could therefore name any
agent and read or write its data -- the scope was real, the owner was not.

This revision adds the missing column and backfills it. The design decisions
worth stating, because they look arbitrary otherwise:

**Backfill target is the local operator, not NULL.** The rows already in the
table belong to the person running the deployment; there is no other candidate.
Writing NULL would leave them invisible to the new owner-scoped queries, which
reads as data loss, and would create rows that no principal can ever read, modify
or delete -- an ownerless row is a row nobody can take away.

**The columns stay nullable, and that is deliberate.** The application layer
refuses to create an unowned row (``MemoryFirewall`` raises; the request routes
derive the owner from the resolved identity). The database is the second line of
defence, not the first, and a NOT NULL constraint here would turn a bug in one
Python path into a migration that fails to deploy. Nullable columns plus a
firewall that refuses to write through them gives the same behaviour with a
recoverable failure mode. Tightening them belongs with real authentication, when
every writer is known.

**``ix_memories_user_created`` and ``ix_memories_user_agent``** exist because
every memory read is now ``WHERE user_id = ...``. Without a leading ``user_id``
index those queries are sequential scans over every user's memories, and the
absence of that index is precisely where a missing owner filter would go
unnoticed under load.

**``permission_requests.user_id`` is included** even though the request flow was
not part of the reported IDOR: a request records a decision the user is about to
be shown and asked to confirm. Recording who it was asked of is what makes
"approve my own request only" checkable at all, and adding it later means
backfilling the audit trail that matters most.

Revision ID: 0008_ownership
Revises: 0007_always_on
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_ownership"
down_revision = "0007_always_on"
branch_labels = None
depends_on = None

#: ``LOCAL_USER_ID`` from ``app.presentation.dependencies.identity``, computed with
#: uuid5(LOCAL_USER_NAMESPACE, "default-user-id"). Spelled out as a literal
#: because a migration must not import application code: if that module changes
#: the constant later, already-migrated databases keep the value they were
#: created with, and re-running the upgrade would produce a different answer.
LOCAL_USER_ID = "b727294b-96c5-571f-be87-476061230075"


def upgrade() -> None:
    op.add_column("agents", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.add_column("agent_runs", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.add_column("memories", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.add_column(
        "permission_requests", sa.Column("user_id", sa.String(36), nullable=True)
    )

    # Backfill before indexing: an index over a column that is mostly NULL is
    # nearly the same size as the table and buys nothing until the data is there.
    op.execute(
        sa.text("UPDATE agents SET user_id = :uid").bindparams(
            uid=sa.cast(sa.literal(LOCAL_USER_ID), sa.Uuid())
        )
    )
    op.execute(
        sa.text("UPDATE agent_runs SET user_id = :uid").bindparams(
            uid=sa.cast(sa.literal(LOCAL_USER_ID), sa.Uuid())
        )
    )
    op.execute(
        sa.text("UPDATE memories SET user_id = :uid").bindparams(
            uid=sa.cast(sa.literal(LOCAL_USER_ID), sa.Uuid())
        )
    )
    op.execute(
        sa.text("UPDATE permission_requests SET user_id = :uid").bindparams(
            uid=LOCAL_USER_ID
        )
    )

    op.create_index("ix_agents_user_id", "agents", ["user_id"])
    op.create_index("ix_agent_runs_user_id", "agent_runs", ["user_id"])
    op.create_index("ix_permission_requests_user_id", "permission_requests", ["user_id"])
    op.create_index(
        "ix_memories_user_created", "memories", ["user_id", "created_at"]
    )
    op.create_index("ix_memories_user_agent", "memories", ["user_id", "agent_id"])


def downgrade() -> None:
    op.drop_index("ix_memories_user_agent", table_name="memories")
    op.drop_index("ix_memories_user_created", table_name="memories")
    op.drop_index("ix_permission_requests_user_id", table_name="permission_requests")
    op.drop_index("ix_agent_runs_user_id", table_name="agent_runs")
    op.drop_index("ix_agents_user_id", table_name="agents")

    op.drop_column("permission_requests", "user_id")
    op.drop_column("memories", "user_id")
    op.drop_column("agent_runs", "user_id")
    op.drop_column("agents", "user_id")