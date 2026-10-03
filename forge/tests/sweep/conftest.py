"""Sweep runner fixtures: throwaway source tree + scratch, seeded containers. INIT-032/SPEC-007."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from forge.sweep import SweepSettings

REQUIRE_NATIVE = os.environ.get("FORGE_REQUIRE_NATIVE") == "1"


def _native_available() -> bool:
    try:
        import forge.engine._libarchive  # noqa: F401
    except (OSError, TypeError, AttributeError, ImportError):
        return False
    return True


NATIVE = _native_available()
if REQUIRE_NATIVE and not NATIVE:
    raise RuntimeError("libarchive.so.13 is required (FORGE_REQUIRE_NATIVE=1)")

needs_native = pytest.mark.skipif(not NATIVE, reason="libarchive.so.13 not available")

FAST_ENV = {
    "FORGE_SWEEP_POLL_SECONDS": "0.1",
    "FORGE_SWEEP_REAP_SECONDS": "0.2",
    "FORGE_SWEEP_HEARTBEAT_SECONDS": "0.5",
    "FORGE_SWEEP_HEARTBEAT_STALE_SECONDS": "3",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class SweepEnv:
    root: Path
    scratch: Path
    db_url: str
    engine: Engine

    def settings(self) -> SweepSettings:
        return SweepSettings.from_env()

    def _source_file(self, conn, rel: str, kind: str) -> int:
        st = (self.root / rel).stat()
        return int(
            conn.execute(
                text(
                    """
                    INSERT INTO source_files (path, size, mtime, kind)
                    VALUES (:p, :s, :m, CAST(:k AS source_file_kind)) RETURNING id
                    """
                ),
                {
                    "p": rel,
                    "s": st.st_size,
                    "m": datetime.fromtimestamp(st.st_mtime, UTC),
                    "k": kind,
                },
            ).scalar_one()
        )

    def _container(self, conn, kind: str, file_ids: list[int], fmt: str | None = None) -> int:
        cid = int(
            conn.execute(
                text(
                    """
                    INSERT INTO containers (source_file_id, kind, format, depth, status)
                    VALUES (:sid, CAST(:k AS container_kind), :fmt, :d, 'pending') RETURNING id
                    """
                ),
                {
                    "sid": file_ids[0] if file_ids else None,
                    "k": kind,
                    "fmt": fmt,
                    "d": 0 if kind == "loose_batch" else 1,
                },
            ).scalar_one()
        )
        for ordinal, sid in enumerate(file_ids, start=1):
            conn.execute(
                text(
                    "INSERT INTO container_files (container_id, source_file_id, ordinal) "
                    "VALUES (:c, :s, :o)"
                ),
                {"c": cid, "s": sid, "o": ordinal},
            )
        return cid

    def write(self, rel: str, data: bytes) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def seed_loose(self, files: dict[str, bytes]) -> int:
        with self.engine.begin() as conn:
            ids = []
            for rel, data in files.items():
                self.write(rel, data)
                ids.append(self._source_file(conn, rel, "loose"))
            return self._container(conn, "loose_batch", ids)

    def seed_archive(self, rel: str, data: bytes | None = None, fmt: str | None = None) -> int:
        if data is not None:
            self.write(rel, data)
        with self.engine.begin() as conn:
            sid = self._source_file(conn, rel, "archive")
            return self._container(conn, "archive", [sid], fmt)

    def scalar(self, sql: str, **params):
        with self.engine.connect() as conn:
            return conn.execute(text(sql), params).scalar()

    def rows(self, sql: str, **params):
        with self.engine.connect() as conn:
            return conn.execute(text(sql), params).mappings().all()


@pytest.fixture
def sweep_env(tmp_path, monkeypatch, session, engine, migrated_db) -> SweepEnv:
    root = tmp_path / "src"
    scratch = tmp_path / "scratch"
    root.mkdir()
    scratch.mkdir()
    monkeypatch.setenv("FORGE_SOURCE_ROOT", str(root))
    monkeypatch.setenv("FORGE_SCRATCH", str(scratch))
    for key, value in FAST_ENV.items():
        monkeypatch.setenv(key, value)
    return SweepEnv(root=root, scratch=scratch, db_url=migrated_db, engine=engine)
