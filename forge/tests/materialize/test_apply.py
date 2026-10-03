"""``forge materialize apply`` end to end on a real catalog, real hardlinks in ``tmp_path``.

AC1 shared blobs stored once + link counts · AC2 verify 0 mismatches · AC3 kill + resume = same
tree · AC4 path escape refused · EXDEV copy fallback · sha mismatch never published · write
audit (every write under v2/scratch) · datapackage provenance. INIT-032/SPEC-012.
"""

from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.materialize.conftest import (
    BASE,
    HERO_BODY,
    KNIGHT,
    SHARED,
    knight_zip,
    needs_native,
    sha,
    stl,
    zip_bytes,
)

pytestmark = needs_native


def store_path(mat, digest: str) -> Path:
    return mat.v2 / ".forge-blobs" / digest[:2] / digest[2:4] / digest


def store_entries(mat) -> list[Path]:
    root = mat.v2 / ".forge-blobs"
    return sorted(p for p in root.rglob("*") if p.is_file())


def pack_status(mat) -> dict[str, str]:
    return {
        r["dir"]: r["status"]
        for r in mat.rows(
            "SELECT dir, status FROM materialize_packs WHERE plan_id = "
            "(SELECT max(id) FROM materialize_plans)"
        )
    }


# ------------------------------------------------------------------------------------- AC1/2


def test_ac1_shared_stls_stored_once_and_hardlinked(library) -> None:
    mat, _ = library
    before = mat.source_snapshot()
    mat.plan()
    assert mat.apply() == 0
    assert pack_status(mat) == {
        "Anime/Hero": "done",
        "Games/Knight": "done",
        "Terrain/Ruins": "done",
    }
    entries = store_entries(mat)
    assert len(entries) == 14
    assert not [p for p in entries if p.name.startswith("tmp-")]
    for name, data in SHARED.items():
        d = sha(data)
        blob = store_path(mat, d).stat()
        hero = (mat.v2 / "Anime/Hero/parts" / name).stat()
        knight = (mat.v2 / "Games/Knight/stl" / name).stat()
        assert blob.st_ino == hero.st_ino == knight.st_ino
        assert blob.st_nlink >= 3  # store + 2 packs (+ the source name when loose)
    # shared1 came from a loose source file: the store entry IS the source inode (no copy).
    src1 = (mat.src / "Anime/Hero/shared1.stl").stat()
    assert store_path(mat, sha(SHARED["shared1.stl"])).stat().st_ino == src1.st_ino
    assert src1.st_nlink == 4
    assert (mat.v2 / "Anime/Hero/extras/bonus/base.stl").read_bytes() == BASE
    assert (mat.v2 / "Anime/Hero/hero_body.stl").read_bytes() == HERO_BODY
    assert (mat.v2 / "Games/Knight/stl/knight.stl").read_bytes() == KNIGHT
    assert mat.source_snapshot() == before


def test_ac2_verify_all_reports_zero_mismatches(library) -> None:
    mat, _ = library
    mat.plan()
    assert mat.apply() == 0
    r = mat.verify(full=True)
    assert r["ok"], r
    assert r["mismatches"] == 0
    c = r["counts"]
    assert c["file_ok_stat"] == 17 and c["file_hardlinked"] == 17
    assert c["sha_ok"] == r["inodes_hashed"] == 14
    assert c.get("stray", 0) == 0
    assert c["nlink_ok"] == 14


def test_rerun_is_idempotent_and_replan_reuses_the_store(library) -> None:
    from forge.materialize.verify import tree_hash

    mat, _ = library
    mat.plan()
    assert mat.apply() == 0
    inodes = {p: p.stat().st_ino for p in mat.v2.rglob("*") if p.is_file()}
    h = tree_hash(mat.v2)
    assert mat.apply() == 0  # nothing pending: no-op
    assert tree_hash(mat.v2) == h
    mat.plan()  # a new plan over the same catalog
    assert mat.apply() == 0
    methods = {
        r["method"]
        for r in mat.rows(
            "SELECT DISTINCT method FROM materialize_blobs WHERE plan_id = "
            "(SELECT max(id) FROM materialize_plans)"
        )
    }
    assert methods == {"existing"}  # no extraction, no new links into the store
    counts = [
        json.loads(r["counts"])
        for r in mat.rows(
            "SELECT counts FROM materialize_packs "
            "WHERE plan_id = (SELECT max(id) FROM "
            "materialize_plans)"
        )
    ]
    assert all(set(c) <= {"skipped", "datapackage"} for c in counts), counts
    for p, ino in inodes.items():
        if p.name != "datapackage.json":
            assert p.stat().st_ino == ino


# ---------------------------------------------------------------------------------------- AC3


def _reset_plan(mat) -> None:
    mat.execute(
        "UPDATE materialize_units SET status = 'pending', attempts = 0, claimed_by = NULL, "
        "claimed_at = NULL, finished_at = NULL, error = NULL"
    )
    mat.execute(
        "UPDATE materialize_blobs SET state = 'pending', method = NULL, error = NULL, "
        "finished_at = NULL WHERE state <> 'missing'"
    )
    mat.execute(
        "UPDATE materialize_packs SET status = 'pending', attempts = 0, claimed_by = NULL, "
        "claimed_at = NULL, finished_at = NULL, error = NULL, counts = NULL"
    )


@pytest.mark.parametrize("kill_after", [2, 5, 12])
def test_ac3_kill_mid_apply_then_resume_gives_identical_tree(library, kill_after) -> None:
    from forge.materialize.verify import tree_hash

    mat, _ = library
    mat.plan()
    assert mat.apply() == 0
    clean = mat.nas / "v2-clean"
    mat.v2.rename(clean)  # keep the uninterrupted tree for comparison (test-side only)
    mat.v2.mkdir()
    _reset_plan(mat)

    env = dict(os.environ, FORGE_MATERIALIZE_TEST_KILL_AFTER=str(kill_after))
    proc = subprocess.run(
        [sys.executable, "-m", "forge.cli", "materialize", "apply"],
        env=env,
        capture_output=True,
        timeout=180,
    )
    assert proc.returncode == -9, proc.stdout.decode()[-2000:] + proc.stderr.decode()[-2000:]
    claimed = mat.scalar(
        "SELECT (SELECT count(*) FROM materialize_units WHERE status = 'claimed') + "
        "(SELECT count(*) FROM materialize_packs WHERE status = 'claimed')"
    )
    assert claimed == 1  # the killed worker's claim is stranded
    assert mat.apply(resume=True) == 0
    assert set(pack_status(mat).values()) == {"done"}
    assert mat.verify(full=True)["ok"]
    assert tree_hash(mat.v2) == tree_hash(clean)


def test_resume_removes_temp_files_of_a_dead_attempt(library) -> None:
    mat, _ = library
    mat.plan()
    unit = mat.rows("SELECT id FROM materialize_units WHERE kind = 'archive' ORDER BY id LIMIT 1")
    uid = unit[0]["id"]
    digest = mat.scalar("SELECT sha256 FROM materialize_blobs WHERE unit_id = :u LIMIT 1", u=uid)
    d = store_path(mat, digest).parent
    d.mkdir(parents=True)
    (d / f"tmp-u{uid}-deadbeef").write_bytes(b"partial")
    mat.execute(
        "UPDATE materialize_units SET status = 'claimed', attempts = 1, "
        "claimed_by = 'dead', claimed_at = now() WHERE id = :u",
        u=uid,
    )
    assert mat.apply(resume=True) == 0
    assert not (d / f"tmp-u{uid}-deadbeef").exists()
    assert mat.verify(full=True)["ok"]


# ------------------------------------------------------------------------- copy fallback


@pytest.mark.parametrize("err", [errno.EXDEV, errno.EPERM])
def test_link_refused_falls_back_to_verified_copies(library, monkeypatch, err) -> None:
    mat, _ = library
    before = mat.source_snapshot()
    mat.plan()

    def no_link(*_a, **_kw):
        raise OSError(err, os.strerror(err))

    monkeypatch.setattr(os, "link", no_link)
    assert mat.apply() == 0
    monkeypatch.undo()
    r = mat.verify(full=True)
    assert r["ok"], r
    assert r["counts"]["file_copy"] == 17 and r["counts"].get("file_hardlinked", 0) == 0
    for p in mat.v2.rglob("*"):
        if p.is_file():
            assert p.stat().st_nlink == 1
    methods = {r["method"] for r in mat.rows("SELECT method FROM materialize_blobs")}
    assert methods == {"copied", "extracted"}
    assert mat.source_snapshot() == before


def test_no_copy_fallback_fails_loudly(library, monkeypatch) -> None:
    mat, _ = library
    mat.plan()

    def no_link(*_a, **_kw):
        raise OSError(errno.EXDEV, "cross-device")

    monkeypatch.setattr(os, "link", no_link)
    assert mat.apply(allow_copy=False) == 1
    monkeypatch.undo()
    loose = mat.rows("SELECT state, error FROM materialize_blobs WHERE source_kind = 'loose'")
    assert {x["state"] for x in loose} == {"failed"}
    assert all("CopyDisabled" in x["error"] for x in loose)


# ------------------------------------------------------------------------------ sha mismatch


def test_sha_mismatch_aborts_without_publishing(library) -> None:
    mat, _ = library
    zp = mat.src / "Games/Knight/Knight.zip"
    st = zp.stat()
    evil = stl("knight-evil", 5)
    assert len(evil) == len(KNIGHT)
    zp.write_bytes(knight_zip(evil))  # same size, same mtime: undetectable by stat
    os.utime(zp, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert zp.stat().st_size == st.st_size
    mat.plan()
    assert mat.apply() == 0
    row = mat.rows("SELECT state, error FROM materialize_blobs WHERE sha256 = :s", s=sha(KNIGHT))[0]
    assert row["state"] == "failed" and row["error"].startswith("sha_mismatch")
    assert not store_path(mat, sha(KNIGHT)).exists()
    assert not store_path(mat, sha(evil)).exists()
    assert not [p for p in store_entries(mat) if p.name.startswith("tmp-")]
    assert not (mat.v2 / "Games/Knight/stl/knight.stl").exists()
    assert pack_status(mat)["Games/Knight"] == "incomplete"
    dp = json.loads((mat.v2 / "Games/Knight/datapackage.json").read_text())
    assert [m["path"] for m in dp["forge"]["missing"]] == ["stl/knight.stl"]
    assert (mat.v2 / "Games/Knight/stl/shared2.stl").exists()


def test_shortage_pack_is_incomplete(library) -> None:
    mat, _ = library
    mat.execute("UPDATE source_files SET present = false WHERE path = 'Games/Knight/Knight.zip'")
    mat.plan()
    assert mat.apply() == 0
    assert pack_status(mat)["Games/Knight"] == "incomplete"
    assert pack_status(mat)["Anime/Hero"] == "done"


# ---------------------------------------------------------------------- guard end to end (AC4)


def test_hostile_plan_path_is_refused_and_source_untouched(library) -> None:
    mat, packs = library
    before = mat.source_snapshot()
    mat.plan()
    mat.execute(
        "UPDATE materialize_files SET rel_path = '../../3D-Prints/pwned.stl' "
        "WHERE pack_id = :p AND rel_path = 'hero_body.stl'",
        p=packs["hero"],
    )
    assert mat.apply() == 3
    row = mat.rows(
        "SELECT status, error FROM materialize_packs WHERE pack_id = :p", p=packs["hero"]
    )[0]
    assert row["status"] == "failed" and "guard_refused" in row["error"]
    assert not (mat.src / "pwned.stl").exists()
    assert not (mat.nas / "pwned.stl").exists()
    assert mat.source_snapshot() == before
    assert pack_status(mat)["Games/Knight"] == "done"


def test_hostile_catalog_source_path_is_refused(library) -> None:
    mat, _ = library
    mat.plan()
    mat.execute(
        "UPDATE materialize_blobs SET source_path = '../../etc/hostname' "
        "WHERE source_path = 'Anime/Hero/hero_body.stl'"
    )
    assert mat.apply() == 3
    assert not list((mat.v2 / ".forge-blobs").rglob("*hostname*"))


# The audit hook cannot be removed once installed; it records only while a sink is set.
_AUDIT: dict = {"installed": False, "sink": None}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_PATH_EVENTS = {
    "os.remove": 0,
    "os.rmdir": 0,
    "os.mkdir": 0,
    "os.chmod": 0,
    "os.chown": 0,
    "os.utime": 0,
    "os.truncate": 0,
    "shutil.rmtree": 0,
    "shutil.copyfile": 1,
    "os.symlink": 1,  # the new link name
    "os.link": 1,  # the NEW name; the link source (a source file) is not modified
}


def _resolve(p) -> str | None:
    if isinstance(p, int) or p is None:
        return None
    p = os.fsdecode(os.fspath(p))
    if not os.path.isabs(p):
        p = os.path.join(os.getcwd(), p)
    return os.path.join(os.path.realpath(os.path.dirname(p)), os.path.basename(p))


def _audit_hook(event: str, args) -> None:
    sink = _AUDIT["sink"]
    if sink is None:
        return
    if event == "open":
        path, mode, flags = args
        writing = (isinstance(mode, str) and set(mode) & set("wax+")) or (
            isinstance(flags, int) and flags & _WRITE_FLAGS
        )
        if writing:
            sink.append(("open", _resolve(path)))
    elif event in ("os.rename", "os.replace"):
        sink += [(event, _resolve(args[0])), (event, _resolve(args[1]))]
    elif event in _PATH_EVENTS:
        sink.append((event, _resolve(args[_PATH_EVENTS[event]])))


def test_every_write_lands_under_v2_or_scratch(library) -> None:
    """Python audit hook over a full apply + verify + gc: every write-ish syscall target resolves
    under the v2 root or scratch, never under the source root."""
    from forge.materialize.apply import active_plan_id
    from forge.materialize.guard import open_guard
    from forge.materialize.verify import gc_plan, verify

    mat, _ = library
    mat.plan()
    v2, scratch, src = (os.path.realpath(p) for p in (mat.v2, mat.scratch, mat.src))
    if not _AUDIT["installed"]:
        sys.addaudithook(_audit_hook)
        _AUDIT["installed"] = True
    events: list[tuple[str, str | None]] = []
    before = mat.source_snapshot()
    _AUDIT["sink"] = events
    try:
        assert mat.apply() == 0
        verify(mat.engine, active_plan_id(mat.engine), mat.v2, full=True)
        g, _ = open_guard(mat.v2, mat.src, mat.scratch, shared_mount_ack=True)
        gc_plan(mat.engine, active_plan_id(mat.engine), g, apply_gc=True)
    finally:
        _AUDIT["sink"] = None
    kinds = {e for e, _ in events}
    assert {"open", "os.link", "os.rename", "os.mkdir", "os.remove"} <= kinds, kinds
    bad = [
        (e, p)
        for e, p in events
        if p is not None
        and "__pycache__" not in p
        and not (p.startswith(v2 + "/") or p.startswith(scratch + "/"))
    ]
    assert bad == []
    assert not [p for _, p in events if p and (p == src or p.startswith(src + "/"))]
    assert mat.source_snapshot() == before


# ---------------------------------------------------------------------------- datapackage


def test_datapackage_provenance(library) -> None:
    mat, packs = library
    res = mat.plan()
    assert mat.apply() == 0
    dp = json.loads((mat.v2 / "Anime/Hero/datapackage.json").read_text())
    assert dp["name"] == "hero" and dp["title"] == "Hero"
    assert dp["category"] == "Anime"
    assert dp["creator"] == "Sculptor X" and dp["source"] == "Cults3D"
    f = dp["forge"]
    assert f["pack_id"] == packs["hero"] and f["plan_id"] == res.plan_id
    assert f["tool"] == "library-forge" and f["tool_version"]
    assert f["materialized_at"].endswith("+00:00")
    assert f["missing"] == []
    paths = {c["kind"]: c["paths"] for c in f["source_containers"]}
    assert paths["archive"] == ["Anime/Hero/Hero.zip"]
    assert paths["loose_batch"] == ["Anime/Hero/hero_body.stl", "Anime/Hero/preview.jpg"]
    res_by_path = {r["path"]: r for r in dp["resources"]}
    assert len(res_by_path) == 7
    assert sorted(f["blob_shas"]) == f["blob_shas"]
    assert set(f["blob_shas"]) == {r["hash"].removeprefix("sha256:") for r in dp["resources"]}
    base = res_by_path["extras/bonus/base.stl"]
    assert base["hash"] == f"sha256:{sha(BASE)}" and base["bytes"] == len(BASE)
    assert base["provenance"]["member_chain"] == ["extras.zip", "bonus/base.stl"]
    assert base["provenance"]["source_path"] == "Anime/Hero/Hero.zip"
    assert base["materialized_from"]["kind"] == "archive"
    s1 = res_by_path["parts/shared1.stl"]
    assert s1["materialized_from"] == {"kind": "loose", "path": "Anime/Hero/shared1.stl"}
    for r in dp["resources"]:
        assert sha((mat.v2 / "Anime/Hero" / r["path"]).read_bytes()) == r["hash"][7:]


def test_collisions_inside_a_pack(mat) -> None:
    a, b = stl("twin-a", 3), stl("twin-b", 3)
    mat.write("Art/Twins/Twins.zip", zip_bytes({"a/Model.stl": a, "a/model.stl": b}))
    mat.catalog()
    pid = mat.pack("Twins", "Art", [(mat.container_of("Art/Twins/Twins.zip"), "primary")])
    mat.plan()
    assert mat.apply() == 0
    d = mat.v2 / "Art/Twins/a"
    assert (d / "Model.stl").read_bytes() == a
    assert (d / f"model~{sha(b)[:8]}.stl").read_bytes() == b
    assert pid


# ------------------------------------------------------------------------------- scope / procs


def test_pack_scope_then_rest(library) -> None:
    mat, packs = library
    mat.plan()
    assert mat.apply(pack_ids=[packs["knight"]]) == 0
    st = pack_status(mat)
    assert st["Games/Knight"] == "done" and st["Anime/Hero"] == "pending"
    assert not (mat.v2 / "Anime/Hero").exists()
    assert mat.apply(limit=1) == 0
    assert sum(1 for v in pack_status(mat).values() if v == "done") == 2
    assert mat.apply() == 0
    assert set(pack_status(mat).values()) == {"done"}


def test_parallel_workers_claim_each_unit_once(library) -> None:
    mat, _ = library
    mat.plan()
    assert mat.apply(procs=3) == 0
    attempts = {r["attempts"] for r in mat.rows("SELECT attempts FROM materialize_units")}
    assert attempts == {1}
    assert set(pack_status(mat).values()) == {"done"}
    assert mat.verify(full=True)["ok"]
