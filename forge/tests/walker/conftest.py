"""Walker fixture tree. INIT-032/SPEC-005."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ZIP_MAGIC = b"PK\x03\x04" + b"\x00" * 12
RAR5_MAGIC = b"Rar!\x1a\x07\x01\x00" + b"\x00" * 8


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture
def fixture_tree(tmp_path: Path) -> Path:
    """Loose STL/JPG, a zip, a 3-part RAR, a gapped RAR, a symlink, a skip dir."""
    _write(tmp_path / "loose" / "model.stl", b"solid fixture\nendsolid\n")
    _write(tmp_path / "loose" / "photo.jpg", b"\xff\xd8\xff\xe0fake-jpeg")
    _write(tmp_path / "archive" / "pack.zip", ZIP_MAGIC + b"zip-body")
    for part in (1, 2, 3):
        _write(tmp_path / "split" / f"set.part{part}.rar", RAR5_MAGIC + bytes([part]))
    _write(tmp_path / "gap" / "broken.part1.rar", RAR5_MAGIC + b"1")
    _write(tmp_path / "gap" / "broken.part3.rar", RAR5_MAGIC + b"3")
    os.symlink(tmp_path / "loose" / "model.stl", tmp_path / "link-to-stl")
    _write(tmp_path / ".manyfold" / "preview.png", b"should-be-skipped")
    return tmp_path


@pytest.fixture
def walked_db(fixture_tree: Path, session, monkeypatch):
    """First walk of the fixture tree against the throwaway test DB."""
    from forge.walker import run

    monkeypatch.setenv("FORGE_SOURCE_ROOT", str(fixture_tree))
    result = run(source_root=fixture_tree, dry_run=False, threads=2)
    session.expire_all()
    return result
