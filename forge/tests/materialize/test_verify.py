"""verify / gc-plan / audit-source / CLI wiring. INIT-032/SPEC-012."""

from __future__ import annotations

import json
import os

from forge.cli import main
from tests.materialize.conftest import SHARED, needs_native, sha

pytestmark = needs_native


def test_verify_detects_corruption_missing_and_strays(library) -> None:
    mat, _ = library
    mat.plan()
    assert mat.apply() == 0
    # Break things the way a human or a bad tool could (test-side, inside v2 only).
    victim = mat.v2 / "Games/Knight/stl/knight.stl"
    victim.unlink()
    victim.write_bytes(b"x")  # wrong size, new inode
    (mat.v2 / "Terrain/Ruins/Ruins/readme.txt").unlink()
    (mat.v2 / "Misc").mkdir()
    (mat.v2 / "Misc/stray.stl").write_bytes(b"stray")
    r = mat.verify(full=True)
    assert not r["ok"]
    c = r["counts"]
    assert c["file_size_mismatch"] == 1
    assert c["file_missing"] == 1
    assert c["stray"] == 1 and r["stray_examples"] == ["Misc/stray.stl"]


def test_verify_detects_same_size_bit_rot(library) -> None:
    mat, _ = library
    mat.plan()
    assert mat.apply() == 0
    p = mat.v2 / "Anime/Hero/parts/shared2.stl"
    data = bytearray(p.read_bytes())
    data[100] ^= 0xFF
    p.unlink()  # new inode: leaves the store entry intact
    p.write_bytes(bytes(data))
    r = mat.verify(full=True)
    assert r["mismatches"] == 1 and not r["ok"]
    assert r["examples"]["sha_mismatch"][0]["path"] == "Anime/Hero/parts/shared2.stl"


def test_gc_plan_lists_and_deletes_only_with_flag(library) -> None:
    from forge.materialize.apply import active_plan_id
    from forge.materialize.guard import open_guard
    from forge.materialize.verify import gc_plan

    mat, _ = library
    before = mat.source_snapshot()
    mat.plan()
    assert mat.apply() == 0
    (mat.v2 / "Old/Pack").mkdir(parents=True)
    (mat.v2 / "Old/Pack/gone.stl").write_bytes(b"gone")
    (mat.v2 / "Anime/Hero/extra.txt").write_bytes(b"extra")
    g, _ = open_guard(mat.v2, mat.src, mat.scratch, shared_mount_ack=True)
    pid = active_plan_id(mat.engine)
    listed = gc_plan(mat.engine, pid, g)
    assert listed["stray_paths"] == ["Anime/Hero/extra.txt", "Old/Pack/gone.stl"]
    assert (mat.v2 / "Old/Pack/gone.stl").exists()
    applied = gc_plan(mat.engine, pid, g, apply_gc=True)
    assert applied["removed_files"] == 2 and applied["removed_dirs"] == 2
    assert not (mat.v2 / "Old").exists()
    assert mat.verify(full=True)["ok"]
    assert mat.source_snapshot() == before
    # a superseded plan's tree is all strays for the new plan's gc — but only under v2
    assert (mat.src / "Anime/Hero/shared1.stl").read_bytes() == SHARED["shared1.stl"]


def test_audit_source_reports_drift(library) -> None:
    from forge.materialize.verify import audit_source

    mat, _ = library
    r = audit_source(mat.engine, mat.src)
    assert r["ok"] and r["counts"]["unchanged"] == r["counts"]["checked"] == 9
    # test-side drift of the fake source tree (the materializer itself never does this)
    p = mat.src / "Anime/Hero/preview.jpg"
    st = p.stat()
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    (mat.src / "Games/Knight/Knight.zip").rename(mat.tmp / "moved.zip")
    r = audit_source(mat.engine, mat.src)
    assert not r["ok"]
    assert r["counts"]["mtime_changed"] == 1 and r["counts"]["missing"] == 1
    assert r["examples"]["missing"] == ["Games/Knight/Knight.zip"]


def test_cli_end_to_end(library, capsys) -> None:
    mat, _ = library
    out = mat.scratch / "plan.jsonl"
    assert main(["materialize", "plan", "--out", str(out)]) == 0
    totals = json.loads(capsys.readouterr().out)
    assert totals["files"] == 17 and totals["free_bytes"] > 0
    lines = out.read_text().splitlines()
    assert json.loads(lines[0])["type"] == "totals" and len(lines) == 4
    assert main(["materialize", "apply", "--procs", "1"]) == 0
    capsys.readouterr()
    assert main(["materialize", "verify", "--all", "--tree-hash"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] and len(report["tree_hash"]) == 64
    assert main(["materialize", "audit-source"]) == 0
    capsys.readouterr()
    assert main(["materialize", "gc-plan"]) == 0
    assert json.loads(capsys.readouterr().out)["strays"] == 0
    assert (mat.v2 / "Games/Knight/stl/shared3.stl").read_bytes() == SHARED["shared3.stl"]
    assert sha((mat.v2 / "Games/Knight/stl/shared3.stl").read_bytes())


def test_cli_plan_out_refuses_paths_outside_v2_and_scratch(library, capsys) -> None:
    mat, _ = library
    assert main(["materialize", "plan", "--out", str(mat.src / "plan.jsonl")]) == 3
    assert "GUARD REFUSED" in capsys.readouterr().err
    assert not (mat.src / "plan.jsonl").exists()


def test_cli_apply_refuses_unacknowledged_shared_mount(library, monkeypatch, capsys) -> None:
    mat, _ = library
    mat.plan()
    monkeypatch.delenv("FORGE_SOURCE_SHARED_MOUNT")
    assert main(["materialize", "apply"]) == 2
    assert "FORGE_SOURCE_SHARED_MOUNT" in capsys.readouterr().err
    assert not (mat.v2 / ".forge-blobs").exists()


def test_cli_requires_roots(monkeypatch, capsys, migrated_db) -> None:
    monkeypatch.delenv("FORGE_V2_ROOT", raising=False)
    assert main(["materialize", "verify"]) == 2
    assert "FORGE_V2_ROOT" in capsys.readouterr().err


def test_preflight_probes_a_real_hardlink_and_leaves_no_trace(library, capsys) -> None:
    mat, _ = library
    before = mat.source_snapshot()
    nlinks = {p: p.stat().st_nlink for p in mat.src.rglob("*") if p.is_file()}
    assert main(["materialize", "preflight"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["link_probe"] == {"ok": True, "same_inode": True}
    assert out["startup"]["same_device"] and out["v2_free_bytes"] > 0
    assert not [p for p in (mat.v2 / ".forge-blobs").iterdir()]
    assert mat.source_snapshot() == before
    assert {p: p.stat().st_nlink for p in mat.src.rglob("*") if p.is_file()} == nlinks


def test_preflight_reports_refused_link(library, monkeypatch, capsys) -> None:
    import errno as _errno

    mat, _ = library

    def no_link(*_a, **_kw):
        raise OSError(_errno.EPERM, "Operation not permitted")

    monkeypatch.setattr(os, "link", no_link)
    assert main(["materialize", "preflight"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["link_probe"]["errno"] == "EPERM"
