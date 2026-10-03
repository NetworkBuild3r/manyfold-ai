"""sweep progress: container timing/notes/requeue link, worker heartbeats

Revision ID: 0002_sweep_progress
Revises: 0001_forge_schema
Create Date: 2026-10-03

INIT-032/SPEC-007
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_sweep_progress"
down_revision: str | Sequence[str] | None = "0001_forge_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("containers", sa.Column("finished_at", sa.DateTime(timezone=True)))
    op.add_column("containers", sa.Column("source_bytes", sa.BigInteger()))
    op.add_column("containers", sa.Column("notes", sa.Text()))
    op.add_column(
        "containers",
        sa.Column(
            "requeued_from_id",
            sa.BigInteger(),
            sa.ForeignKey("containers.id", ondelete="SET NULL"),
        ),
    )
    op.create_index(
        "ix_containers_finished_at",
        "containers",
        ["finished_at"],
        postgresql_where=sa.text("finished_at IS NOT NULL"),
    )
    op.create_index(
        "ix_containers_claimed",
        "containers",
        ["claimed_at"],
        postgresql_where=sa.text("status = 'claimed'"),
    )
    op.create_index(
        "ix_containers_parent",
        "containers",
        ["parent_container_id"],
        postgresql_where=sa.text("parent_container_id IS NOT NULL"),
    )
    op.create_index(
        "ix_containers_requeued_from",
        "containers",
        ["requeued_from_id"],
        postgresql_where=sa.text("requeued_from_id IS NOT NULL"),
    )

    op.create_table(
        "sweep_workers",
        sa.Column("worker_id", sa.Text(), primary_key=True),
        sa.Column(
            "sweep_run_id",
            sa.BigInteger(),
            sa.ForeignKey("sweep_runs.id", ondelete="SET NULL"),
        ),
        sa.Column("host", sa.Text()),
        sa.Column("pid", sa.Integer()),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "last_seen", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("current_container_id", sa.BigInteger()),
        sa.Column("containers_done", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "containers_failed", sa.BigInteger(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("bytes_read", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("source_bytes", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_table("sweep_workers")
    op.drop_index("ix_containers_requeued_from", table_name="containers")
    op.drop_index("ix_containers_parent", table_name="containers")
    op.drop_index("ix_containers_claimed", table_name="containers")
    op.drop_index("ix_containers_finished_at", table_name="containers")
    op.drop_column("containers", "requeued_from_id")
    op.drop_column("containers", "notes")
    op.drop_column("containers", "source_bytes")
    op.drop_column("containers", "finished_at")
