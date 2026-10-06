"""Test helpers shared by schema tests. INIT-032/SPEC-004."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from forge.db.enums import BlobKind, ContainerKind, ContainerStatus
from forge.db.models import Blob, Container

CATALOG_TABLES = (
    "sweep_workers",
    "pack_decisions",
    "pack_containers",
    "packs",
    "occurrences",
    "container_files",
    "containers",
    "source_files",
    "blobs",
    "sweep_runs",
)


def hex_sha(seed: bytes) -> str:
    return hashlib.sha256(seed).hexdigest()


def add_blob(session: Session, seed: bytes = b"blob", **kwargs) -> Blob:
    blob = Blob(
        sha256=kwargs.pop("sha256", hex_sha(seed)),
        size=kwargs.pop("size", len(seed)),
        kind=kwargs.pop("kind", BlobKind.mesh),
        ext=kwargs.pop("ext", "stl"),
        **kwargs,
    )
    session.add(blob)
    session.flush()
    return blob


def add_container(session: Session, **kwargs) -> Container:
    container = Container(
        kind=kwargs.pop("kind", ContainerKind.archive),
        format=kwargs.pop("format", "zip"),
        depth=kwargs.pop("depth", 1),
        status=kwargs.pop("status", ContainerStatus.pending),
        **kwargs,
    )
    session.add(container)
    session.flush()
    return container


def utcnow() -> datetime:
    return datetime.now(UTC)
