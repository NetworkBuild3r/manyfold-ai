"""SQLAlchemy 2.x models for the forge catalog.

Field list follows ADR D-1 plus the SPEC-004 / engine-contract notes
(containers.kind, container_files, parent_chain, blob_sha, member_chain).
ADR parent_blob is this model's Container.blob_sha.

INIT-032/SPEC-004
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from forge.db.enums import (
    PACK_CATEGORIES,
    BlobKind,
    ContainerKind,
    ContainerStatus,
    FailureReason,
    PackContainerRole,
    PackDecisionKind,
    PackStatus,
    PackVerdict,
    SourceFileKind,
    SweepKind,
)

# Unit separator — refuse.py strips control chars, so this cannot appear in a member name.
MEMBER_PATH_SEP = "\x1f"


def join_member_path(chain: Sequence[str]) -> str:
    """Joined text used by uq_occurrences_container_member_path."""
    if not chain:
        raise ValueError("member_chain must not be empty")
    return MEMBER_PATH_SEP.join(chain)


def _pg_enum(enum_cls: type, name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        native_enum=True,
        create_constraint=False,
        values_callable=lambda members: [m.value for m in members],
    )


class Base(DeclarativeBase):
    pass


class SweepRun(Base):
    __tablename__ = "sweep_runs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[SweepKind] = mapped_column(_pg_enum(SweepKind, "sweep_kind"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(Text)
    files_seen: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    files_new: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    files_unchanged: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    files_changed: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    files_vanished: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    containers_seeded: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    containers_claimed: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    containers_done: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    containers_failed: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    blobs_created: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    occurrences_created: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    bytes_read: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    notes: Mapped[str | None] = mapped_column(Text)


class SweepWorker(Base):
    """Heartbeat + counters per sweep worker process (SPEC-007)."""

    __tablename__ = "sweep_workers"

    worker_id: Mapped[str] = mapped_column(Text, primary_key=True)
    sweep_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sweep_runs.id", ondelete="SET NULL")
    )
    host: Mapped[str | None] = mapped_column(Text)
    pid: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    current_container_id: Mapped[int | None] = mapped_column(BigInteger)
    containers_done: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    containers_failed: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    bytes_read: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    source_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))


class Blob(Base):
    __tablename__ = "blobs"
    __table_args__ = (CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_blobs_sha256_hex"),)

    sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[BlobKind] = mapped_column(_pg_enum(BlobKind, "blob_kind"), nullable=False)
    ext: Mapped[str | None] = mapped_column(Text)
    stl_triangles: Mapped[int | None] = mapped_column(Integer)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    occurrences: Mapped[list[Occurrence]] = relationship(back_populates="blob")


class SourceFile(Base):
    __tablename__ = "source_files"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mtime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    kind: Mapped[SourceFileKind] = mapped_column(
        _pg_enum(SourceFileKind, "source_file_kind"), nullable=False
    )
    format: Mapped[str | None] = mapped_column(Text)
    volume_set: Mapped[str | None] = mapped_column(Text)
    first_seen_sweep: Mapped[int | None] = mapped_column(
        ForeignKey("sweep_runs.id", ondelete="SET NULL")
    )
    last_seen_sweep: Mapped[int | None] = mapped_column(
        ForeignKey("sweep_runs.id", ondelete="SET NULL")
    )
    present: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    container_files: Mapped[list[ContainerFile]] = relationship(back_populates="source_file")


class Container(Base):
    __tablename__ = "containers"
    __table_args__ = (
        Index(
            "ix_containers_pending_claim",
            "status",
            "id",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_containers_finished_at",
            "finished_at",
            postgresql_where=text("finished_at IS NOT NULL"),
        ),
        Index("ix_containers_claimed", "claimed_at", postgresql_where=text("status = 'claimed'")),
        Index(
            "ix_containers_parent",
            "parent_container_id",
            postgresql_where=text("parent_container_id IS NOT NULL"),
        ),
        Index(
            "ix_containers_requeued_from",
            "requeued_from_id",
            postgresql_where=text("requeued_from_id IS NOT NULL"),
        ),
        Index(
            "ix_containers_superseded_by",
            "superseded_by_id",
            postgresql_where=text("superseded_by_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_files.id", ondelete="SET NULL")
    )
    # ADR D-1 parent_blob — nested archive's own blob.
    blob_sha: Mapped[str | None] = mapped_column(ForeignKey("blobs.sha256", ondelete="RESTRICT"))
    parent_container_id: Mapped[int | None] = mapped_column(
        ForeignKey("containers.id", ondelete="RESTRICT")
    )
    parent_chain: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    kind: Mapped[ContainerKind] = mapped_column(
        _pg_enum(ContainerKind, "container_kind"), nullable=False
    )
    format: Mapped[str | None] = mapped_column(Text)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    status: Mapped[ContainerStatus] = mapped_column(
        _pg_enum(ContainerStatus, "container_status"),
        nullable=False,
        server_default=text("'pending'"),
    )
    failure_reason: Mapped[FailureReason | None] = mapped_column(
        _pg_enum(FailureReason, "failure_reason")
    )
    claimed_by: Mapped[str | None] = mapped_column(Text)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    members: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    bytes_read: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    # SPEC-007: sum of the source file sizes (NAS bytes), set when a sweep worker claims it.
    source_bytes: Mapped[int | None] = mapped_column(BigInteger)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # JSON: reader/detail/peak RSS, refusals by reason, superseded_by / requeued_from.
    notes: Mapped[str | None] = mapped_column(Text)
    # A loose_batch re-queued from an archive container that was not an archive at all.
    requeued_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("containers.id", ondelete="SET NULL")
    )
    # 0007: a volume (2..N) that was catalogued alone before its multi-volume set was resolved.
    # Points at the set container (the one whose container_files hold every volume). Superseded
    # rows are 'done' with no members/source files/source bytes; every count and unit skips them.
    superseded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("containers.id", ondelete="SET NULL")
    )

    source_file: Mapped[SourceFile | None] = relationship()
    parent: Mapped[Container | None] = relationship(
        remote_side="Container.id", foreign_keys=[parent_container_id]
    )
    files: Mapped[list[ContainerFile]] = relationship(back_populates="container")
    occurrences: Mapped[list[Occurrence]] = relationship(back_populates="container")


class ContainerFile(Base):
    """Volume set / loose_batch membership. ordinal is 1-based volume order."""

    __tablename__ = "container_files"
    __table_args__ = (
        UniqueConstraint("container_id", "ordinal", name="uq_container_files_ordinal"),
    )

    container_id: Mapped[int] = mapped_column(
        ForeignKey("containers.id", ondelete="CASCADE"), primary_key=True
    )
    source_file_id: Mapped[int] = mapped_column(
        ForeignKey("source_files.id", ondelete="CASCADE"), primary_key=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    container: Mapped[Container] = relationship(back_populates="files")
    source_file: Mapped[SourceFile] = relationship(back_populates="container_files")


class Occurrence(Base):
    __tablename__ = "occurrences"
    __table_args__ = (
        UniqueConstraint(
            "container_id", "member_path", name="uq_occurrences_container_member_path"
        ),
        Index("ix_occurrences_blob_sha", "blob_sha"),
        Index("ix_occurrences_container_id", "container_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    blob_sha: Mapped[str] = mapped_column(
        ForeignKey("blobs.sha256", ondelete="RESTRICT"), nullable=False
    )
    container_id: Mapped[int] = mapped_column(
        ForeignKey("containers.id", ondelete="CASCADE"), nullable=False
    )
    member_chain: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    member_path: Mapped[str] = mapped_column(Text, nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)

    blob: Mapped[Blob] = relationship(back_populates="occurrences")
    container: Mapped[Container] = relationship(back_populates="occurrences")

    @classmethod
    def from_chain(
        cls,
        *,
        blob_sha: str,
        container_id: int,
        member_chain: Sequence[str],
        depth: int,
    ) -> Occurrence:
        return cls(
            blob_sha=blob_sha,
            container_id=container_id,
            member_chain=list(member_chain),
            member_path=join_member_path(member_chain),
            depth=depth,
        )


class Pack(Base):
    __tablename__ = "packs"
    __table_args__ = (
        CheckConstraint(
            f"category IS NULL OR category IN ({', '.join(repr(c) for c in PACK_CATEGORIES)})",
            name="ck_packs_category",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    creator: Mapped[str | None] = mapped_column(Text)
    source_tag: Mapped[str | None] = mapped_column(Text)
    status: Mapped[PackStatus] = mapped_column(
        _pg_enum(PackStatus, "pack_status"),
        nullable=False,
        server_default=text("'provisional'"),
    )
    needs_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    decided_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    containers: Mapped[list[PackContainer]] = relationship(back_populates="pack")


class PackContainer(Base):
    __tablename__ = "pack_containers"

    pack_id: Mapped[int] = mapped_column(
        ForeignKey("packs.id", ondelete="CASCADE"), primary_key=True
    )
    container_id: Mapped[int] = mapped_column(
        ForeignKey("containers.id", ondelete="RESTRICT"), primary_key=True
    )
    role: Mapped[PackContainerRole] = mapped_column(
        _pg_enum(PackContainerRole, "pack_container_role"), nullable=False
    )

    pack: Mapped[Pack] = relationship(back_populates="containers")
    container: Mapped[Container] = relationship()


class PackDecision(Base):
    __tablename__ = "pack_decisions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[PackDecisionKind] = mapped_column(
        _pg_enum(PackDecisionKind, "pack_decision_kind"), nullable=False
    )
    container_a: Mapped[int] = mapped_column(
        ForeignKey("containers.id", ondelete="RESTRICT"), nullable=False
    )
    container_b: Mapped[int] = mapped_column(
        ForeignKey("containers.id", ondelete="RESTRICT"), nullable=False
    )
    verdict: Mapped[PackVerdict] = mapped_column(
        _pg_enum(PackVerdict, "pack_verdict"), nullable=False
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    rationale: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    input_fingerprint: Mapped[str | None] = mapped_column(Text)
    human_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
