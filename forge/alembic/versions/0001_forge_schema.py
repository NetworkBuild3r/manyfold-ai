"""forge catalog schema

Revision ID: 0001_forge_schema
Revises:
Create Date: 2026-10-03

INIT-032/SPEC-004
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_forge_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *labels: str) -> postgresql.ENUM:
    return postgresql.ENUM(*labels, name=name, create_type=False)


SOURCE_FILE_KIND = _enum("source_file_kind", "archive", "loose")
CONTAINER_KIND = _enum("container_kind", "archive", "loose_batch", "nested")
CONTAINER_STATUS = _enum("container_status", "pending", "claimed", "done", "failed")
FAILURE_REASON = _enum(
    "failure_reason",
    "depth_exceeded",
    "ratio_exceeded",
    "member_too_large",
    "spool_exceeded",
    "total_too_large",
    "timeout",
    "reader_error",
    "unsupported_format",
    "missing_volume",
    "encrypted",
    "oom",
    "retries_exhausted",
)
BLOB_KIND = _enum("blob_kind", "mesh", "image", "archive", "doc", "other")
SWEEP_KIND = _enum("sweep_kind", "walk", "sweep")
PACK_STATUS = _enum("pack_status", "provisional", "resolved", "materialized")
PACK_CONTAINER_ROLE = _enum("pack_container_role", "primary", "source", "absorbed")
PACK_DECISION_KIND = _enum("pack_decision_kind", "deterministic", "llm", "human")
PACK_VERDICT = _enum("pack_verdict", "same_pack", "separate", "unsure", "absorb")

ENUMS = (
    SOURCE_FILE_KIND,
    CONTAINER_KIND,
    CONTAINER_STATUS,
    FAILURE_REASON,
    BLOB_KIND,
    SWEEP_KIND,
    PACK_STATUS,
    PACK_CONTAINER_ROLE,
    PACK_DECISION_KIND,
    PACK_VERDICT,
)

PACK_CATEGORIES_SQL = (
    "category IS NULL OR category IN ("
    "'Anime','Cartoons','Cosplay','DC','D&D','Games','Movie TV',"
    "'Comics','Vehicles','Terrain','Tabletop','Art','Tools','Misc')"
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum in ENUMS:
        postgresql.ENUM(*enum.enums, name=enum.name).create(bind, checkfirst=True)

    op.create_table(
        "sweep_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("kind", SWEEP_KIND, nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.Text(), nullable=True),
        sa.Column("files_seen", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("files_new", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("files_unchanged", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("files_changed", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("files_vanished", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("containers_seeded", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("containers_claimed", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("containers_done", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("containers_failed", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("blobs_created", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("occurrences_created", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("bytes_read", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    op.create_table(
        "blobs",
        sa.Column("sha256", sa.Text(), primary_key=True),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("kind", BLOB_KIND, nullable=False),
        sa.Column("ext", sa.Text(), nullable=True),
        sa.Column("stl_triangles", sa.Integer(), nullable=True),
        sa.Column(
            "first_seen",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_blobs_sha256_hex"),
    )

    op.create_table(
        "source_files",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("mtime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", SOURCE_FILE_KIND, nullable=False),
        sa.Column("format", sa.Text(), nullable=True),
        sa.Column("volume_set", sa.Text(), nullable=True),
        sa.Column("first_seen_sweep", sa.BigInteger(), nullable=True),
        sa.Column("last_seen_sweep", sa.BigInteger(), nullable=True),
        sa.Column("present", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.ForeignKeyConstraint(["first_seen_sweep"], ["sweep_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["last_seen_sweep"], ["sweep_runs.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("path", name="uq_source_files_path"),
    )

    op.create_table(
        "containers",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source_file_id", sa.BigInteger(), nullable=True),
        sa.Column("blob_sha", sa.Text(), nullable=True),
        sa.Column("parent_container_id", sa.BigInteger(), nullable=True),
        sa.Column("parent_chain", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("kind", CONTAINER_KIND, nullable=False),
        sa.Column("format", sa.Text(), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "status",
            CONTAINER_STATUS,
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("failure_reason", FAILURE_REASON, nullable=True),
        sa.Column("claimed_by", sa.Text(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("members", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bytes_read", sa.BigInteger(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["blob_sha"], ["blobs.sha256"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["parent_container_id"], ["containers.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_containers_pending_claim",
        "containers",
        ["status", "id"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "container_files",
        sa.Column("container_id", sa.BigInteger(), nullable=False),
        sa.Column("source_file_id", sa.BigInteger(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["container_id"], ["containers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("container_id", "source_file_id"),
        sa.UniqueConstraint("container_id", "ordinal", name="uq_container_files_ordinal"),
    )

    op.create_table(
        "occurrences",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("blob_sha", sa.Text(), nullable=False),
        sa.Column("container_id", sa.BigInteger(), nullable=False),
        sa.Column("member_chain", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("member_path", sa.Text(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["blob_sha"], ["blobs.sha256"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["container_id"], ["containers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "container_id",
            "member_path",
            name="uq_occurrences_container_member_path",
        ),
    )
    op.create_index("ix_occurrences_blob_sha", "occurrences", ["blob_sha"])
    op.create_index("ix_occurrences_container_id", "occurrences", ["container_id"])

    op.create_table(
        "packs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("creator", sa.Text(), nullable=True),
        sa.Column("source_tag", sa.Text(), nullable=True),
        sa.Column(
            "status",
            PACK_STATUS,
            nullable=False,
            server_default=sa.text("'provisional'"),
        ),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("decided_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(PACK_CATEGORIES_SQL, name="ck_packs_category"),
    )

    op.create_table(
        "pack_containers",
        sa.Column("pack_id", sa.BigInteger(), nullable=False),
        sa.Column("container_id", sa.BigInteger(), nullable=False),
        sa.Column("role", PACK_CONTAINER_ROLE, nullable=False),
        sa.ForeignKeyConstraint(["pack_id"], ["packs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["container_id"], ["containers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("pack_id", "container_id"),
    )

    op.create_table(
        "pack_decisions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("kind", PACK_DECISION_KIND, nullable=False),
        sa.Column("container_a", sa.BigInteger(), nullable=False),
        sa.Column("container_b", sa.BigInteger(), nullable=False),
        sa.Column("verdict", PACK_VERDICT, nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("input_fingerprint", sa.Text(), nullable=True),
        sa.Column(
            "human_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["container_a"], ["containers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["container_b"], ["containers.id"], ondelete="RESTRICT"),
    )


def downgrade() -> None:
    op.drop_table("pack_decisions")
    op.drop_table("pack_containers")
    op.drop_table("packs")
    op.drop_index("ix_occurrences_container_id", table_name="occurrences")
    op.drop_index("ix_occurrences_blob_sha", table_name="occurrences")
    op.drop_table("occurrences")
    op.drop_table("container_files")
    op.drop_index("ix_containers_pending_claim", table_name="containers")
    op.drop_table("containers")
    op.drop_table("source_files")
    op.drop_table("blobs")
    op.drop_table("sweep_runs")
    bind = op.get_bind()
    for enum in reversed(ENUMS):
        postgresql.ENUM(*enum.enums, name=enum.name).drop(bind, checkfirst=True)
