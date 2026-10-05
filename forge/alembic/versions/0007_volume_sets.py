"""volume sets: containers.superseded_by_id

Revision ID: 0007_volume_sets
Revises: 0006_tags
Create Date: 2026-10-05

INIT-032/SPEC-007. A multi-volume archive is ONE container whose ``container_files`` list every
volume in order (ordinal 1 = first volume = ``containers.source_file_id``), also when the volumes
sit in sibling ``<set>.partN/`` folders. A volume that was catalogued as its own container before
the set was resolved (volume 2..N, or volume 1 when another container owns the set) is not
deleted — packs and decisions may still reference it — but marked ``superseded_by_id`` -> the set
container, ``done`` with no members, no source bytes and no source files. Units, reports and
``forge status`` skip superseded rows, so a set is never counted twice.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007_volume_sets"
down_revision: str | Sequence[str] | None = "0006_tags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE containers
            ADD COLUMN superseded_by_id bigint REFERENCES containers (id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        CREATE INDEX ix_containers_superseded_by ON containers (superseded_by_id)
            WHERE superseded_by_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_containers_superseded_by")
    op.execute("ALTER TABLE containers DROP COLUMN IF EXISTS superseded_by_id")
