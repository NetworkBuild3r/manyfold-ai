"""Extraction across the engine's reader paths: libarchive (RAR4, raw-split 7z, 3-level nesting
zip -> 7z), gzip stream, and the 7zz fallback (Deflate64). Every planned member must come out
byte-exact. INIT-032/SPEC-012."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.engine.fallback import find_7zz
from tests.materialize.conftest import FIXTURES, needs_native

pytestmark = needs_native
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text())


@pytest.mark.skipif(find_7zz() is None, reason="7zz not installed (set FORGE_7ZZ)")
def test_every_reader_path_extracts_byte_exact(mat) -> None:
    layout = {
        "deflate64.zip": "Tools/Kit/deflate64.zip",
        "model.stl.gz": "Tools/Kit/model.stl.gz",
        "depth3.rar": "Tools/Kit/depth3.rar",
        "basic_rar4.rar": "Tools/Kit/basic_rar4.rar",
        "split_raw.7z.001": "Tools/Kit/split_raw.7z.001",
        "split_raw.7z.002": "Tools/Kit/split_raw.7z.002",
        "split_raw.7z.003": "Tools/Kit/split_raw.7z.003",
    }
    for name, rel in layout.items():
        mat.copy_fixture(name, rel)
    mat.catalog()
    roots = sorted(
        {mat.container_of(rel) for rel in layout.values() if not rel.endswith((".002", ".003"))}
    )
    readers = {
        r["id"]: json.loads(r["notes"] or "{}").get("reader")
        for r in mat.rows(
            "SELECT id, notes FROM containers WHERE id = ANY(CAST(:ids AS bigint[]))", ids=roots
        )
    }
    assert "7zz" in readers.values(), readers  # Deflate64 went through the fallback
    pid = mat.pack("Kit", "Tools", [(cid, "primary") for cid in roots])
    res = mat.plan()
    assert res.totals["missing_blobs"] == 0
    assert mat.apply() == 0
    report = mat.verify(full=True)
    assert report["ok"], report
    files = mat.rows("SELECT rel_path, sha256 FROM materialize_files WHERE pack_id = :p", p=pid)
    paths = {f["rel_path"] for f in files}
    assert "depth3/mid/inner/model.stl" in paths  # rar -> zip -> 7z -> member
    assert "model.stl/model.stl" in paths or "model/model.stl" in paths
    want = {
        m["sha256"]
        for entry in MANIFEST.values()
        for m in entry["members"]
        if Path(m["chain"][-1]).suffix.lower() in {".stl", ".png", ".txt"}
    }
    got = {f["sha256"] for f in files}
    assert got <= want
    states = {r["state"] for r in mat.rows("SELECT state FROM materialize_blobs")}
    assert states == {"done"}


@pytest.mark.skipif(find_7zz() is None, reason="7zz not installed (set FORGE_7ZZ)")
def test_7zz_fallback_extracts_only_planned_members(mat, monkeypatch) -> None:
    from forge.materialize.extract import Extractor

    mat.copy_fixture("deflate64.zip", "Tools/Old/deflate64.zip")
    mat.catalog()
    cid = mat.container_of("Tools/Old/deflate64.zip")
    mat.pack("Old", "Tools", [(cid, "primary")])
    mat.plan()
    calls = []
    real = Extractor._sevenzip

    def spy(self, paths, prefix, depth, hint):
        calls.append((len(self.pending), sorted(self.pending)))
        return real(self, paths, prefix, depth, hint)

    monkeypatch.setattr(Extractor, "_sevenzip", spy)
    assert mat.apply() == 0
    assert calls, "libarchive should fail on Deflate64 and hand over to 7zz"
    # random.bin is kind 'other': never planned, so never asked of 7zz
    assert all(("data/random.bin",) not in pending for _, pending in calls)
    assert mat.verify(full=True)["ok"]
    assert not list(mat.scratch.iterdir())  # per-run scratch dirs removed
