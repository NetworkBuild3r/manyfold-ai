"""Catalog builders for report fixtures. INIT-032/SPEC-009."""

from __future__ import annotations

from sqlalchemy.orm import Session
from tests.helpers import add_container, hex_sha, utcnow

from forge.db.enums import BlobKind, ContainerKind, ContainerStatus, SourceFileKind
from forge.db.models import Blob, ContainerFile, Occurrence, SourceFile


def get_or_add_blob(session: Session, seed: bytes, **kwargs) -> Blob:
    sha = kwargs.pop("sha256", hex_sha(seed))
    existing = session.get(Blob, sha)
    if existing is not None:
        return existing
    blob = Blob(
        sha256=sha,
        size=kwargs.pop("size", len(seed)),
        kind=kwargs.pop("kind", BlobKind.mesh),
        ext=kwargs.pop("ext", "stl"),
        **kwargs,
    )
    session.add(blob)
    session.flush()
    return blob


def add_source(
    session: Session,
    path: str,
    *,
    kind: SourceFileKind = SourceFileKind.archive,
    size: int = 100,
    fmt: str | None = "zip",
) -> SourceFile:
    row = SourceFile(path=path, size=size, mtime=utcnow(), kind=kind, format=fmt)
    session.add(row)
    session.flush()
    return row


def add_archive_pack(
    session: Session,
    path: str,
    archive_bytes: bytes,
    members: list[tuple[bytes, str, int, int]],
    *,
    fmt: str = "zip",
) -> tuple[SourceFile, object]:
    """Top-level archive whose ``blob_sha`` is the archive file hash.

    *members* is ``(payload, member_name, size, triangles)``.
    """
    archive_blob = get_or_add_blob(
        session,
        archive_bytes,
        sha256=hex_sha(archive_bytes),
        size=len(archive_bytes),
        kind=BlobKind.archive,
        ext=fmt,
    )
    source = add_source(session, path, size=len(archive_bytes), fmt=fmt)
    container = add_container(
        session,
        kind=ContainerKind.archive,
        format=fmt,
        depth=1,
        status=ContainerStatus.done,
        source_file_id=source.id,
        blob_sha=archive_blob.sha256,
        members=len(members),
        bytes_read=sum(size for _p, _n, size, _t in members),
    )
    session.add(ContainerFile(container_id=container.id, source_file_id=source.id, ordinal=1))
    for payload, name, size, triangles in members:
        blob = get_or_add_blob(
            session,
            payload,
            sha256=hex_sha(payload),
            size=size,
            kind=BlobKind.mesh,
            ext="stl",
            stl_triangles=triangles,
        )
        session.add(
            Occurrence.from_chain(
                blob_sha=blob.sha256,
                container_id=container.id,
                member_chain=(name,),
                depth=1,
            )
        )
    session.flush()
    return source, container


def add_nested_mesh(
    session: Session,
    outer_path: str,
    outer_bytes: bytes,
    inner_name: str,
    inner_bytes: bytes,
    mesh_payload: bytes,
    mesh_name: str,
    *,
    size: int,
    triangles: int,
) -> None:
    """Outer archive → nested inner archive → mesh (chain-rendered path)."""
    outer_blob = get_or_add_blob(
        session,
        outer_bytes,
        sha256=hex_sha(outer_bytes),
        size=len(outer_bytes),
        kind=BlobKind.archive,
        ext="rar",
    )
    inner_blob = get_or_add_blob(
        session,
        inner_bytes,
        sha256=hex_sha(inner_bytes),
        size=len(inner_bytes),
        kind=BlobKind.archive,
        ext="zip",
    )
    mesh = get_or_add_blob(
        session,
        mesh_payload,
        sha256=hex_sha(mesh_payload),
        size=size,
        kind=BlobKind.mesh,
        ext="stl",
        stl_triangles=triangles,
    )
    source = add_source(session, outer_path, size=len(outer_bytes), fmt="rar")
    outer = add_container(
        session,
        kind=ContainerKind.archive,
        format="rar",
        depth=1,
        status=ContainerStatus.done,
        source_file_id=source.id,
        blob_sha=outer_blob.sha256,
        members=1,
    )
    session.add(ContainerFile(container_id=outer.id, source_file_id=source.id, ordinal=1))
    inner = add_container(
        session,
        kind=ContainerKind.nested,
        format="zip",
        depth=2,
        status=ContainerStatus.done,
        source_file_id=source.id,
        blob_sha=inner_blob.sha256,
        parent_container_id=outer.id,
        parent_chain=[inner_name],
        members=1,
    )
    session.add(
        Occurrence.from_chain(
            blob_sha=mesh.sha256,
            container_id=inner.id,
            member_chain=(inner_name, mesh_name),
            depth=2,
        )
    )
    session.flush()


def add_loose_mesh(
    session: Session,
    path: str,
    payload: bytes,
    *,
    size: int,
    triangles: int,
) -> None:
    source = add_source(session, path, kind=SourceFileKind.loose, size=size, fmt="stl")
    container = add_container(
        session,
        kind=ContainerKind.loose_batch,
        format=None,
        depth=0,
        status=ContainerStatus.done,
        source_file_id=source.id,
        members=1,
    )
    session.add(ContainerFile(container_id=container.id, source_file_id=source.id, ordinal=1))
    blob = get_or_add_blob(
        session,
        payload,
        sha256=hex_sha(payload),
        size=size,
        kind=BlobKind.mesh,
        ext="stl",
        stl_triangles=triangles,
    )
    session.add(
        Occurrence.from_chain(
            blob_sha=blob.sha256,
            container_id=container.id,
            member_chain=(path,),
            depth=0,
        )
    )
    session.flush()
