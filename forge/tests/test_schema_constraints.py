"""AC2 — database constraints reject illegal catalog rows.

INIT-032/SPEC-004
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError

from forge.db.enums import SourceFileKind
from forge.db.models import Occurrence, SourceFile
from tests.helpers import add_blob, add_container, utcnow


def test_duplicate_container_member_path_rejected(session) -> None:
    blob = add_blob(session, b"same-bytes")
    container = add_container(session)
    session.add(
        Occurrence.from_chain(
            blob_sha=blob.sha256,
            container_id=container.id,
            member_chain=("dir/model.stl",),
            depth=1,
        )
    )
    session.flush()
    session.add(
        Occurrence.from_chain(
            blob_sha=blob.sha256,
            container_id=container.id,
            member_chain=("dir/model.stl",),
            depth=1,
        )
    )
    with pytest.raises(IntegrityError, match="uq_occurrences_container_member_path"):
        session.flush()


def test_occurrence_unknown_blob_rejected(session) -> None:
    container = add_container(session)
    missing = "0" * 64
    session.add(
        Occurrence.from_chain(
            blob_sha=missing,
            container_id=container.id,
            member_chain=("ghost.stl",),
            depth=1,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_container_status_outside_enum_rejected(session) -> None:
    session.rollback()
    with pytest.raises(DataError, match="invalid input value for enum container_status"):
        session.execute(
            text(
                """
                INSERT INTO containers (kind, format, depth, status)
                VALUES ('archive', 'zip', 1, 'bogus')
                """
            )
        )
        session.flush()


def test_source_files_path_unique(session) -> None:
    row = SourceFile(
        path="Anime/pack/model.zip",
        size=10,
        mtime=utcnow(),
        kind=SourceFileKind.archive,
        format="zip",
    )
    session.add(row)
    session.flush()
    session.add(
        SourceFile(
            path="Anime/pack/model.zip",
            size=11,
            mtime=utcnow(),
            kind=SourceFileKind.archive,
            format="zip",
        )
    )
    with pytest.raises(IntegrityError, match="uq_source_files_path"):
        session.flush()
