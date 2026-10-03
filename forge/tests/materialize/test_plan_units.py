"""``forge materialize plan`` reads loose ``pack_units`` / ``pack_unit_sources``. INIT-032/SPEC-012.

A ``loose_batch`` holds up to 500 files from many folders. The pack resolver lists a batch in
``pack_containers`` only when ALL its files belong to one pack; a split batch is recorded as loose
units (``pack_units.pack_id`` + ``role``) whose exact members are ``pack_unit_sources``. The planner
must put each unit's source files into that unit's pack — and nothing else.
"""

from __future__ import annotations

from sqlalchemy import text

from tests.materialize.conftest import JPEG, MatEnv, needs_native, sha, stl

pytestmark = needs_native

BODY = stl("alpha-body", 5)
PART_UP = stl("alpha-part-up", 3)
PART_LOW = stl("alpha-part-low", 3)
WING = stl("beta-wing", 4)
TAIL = stl("beta-tail", 4)
COMMON = stl("shared-common", 6)
LOST = stl("orphan-lost", 2)


def _unit(
    mat: MatEnv, key: str, files: list[str], *, pack_id: int | None = None, role: str | None = None
) -> int:
    with mat.engine.begin() as conn:
        uid = int(
            conn.execute(
                text(
                    """
                    INSERT INTO pack_units (unit_key, kind, path, present, complete, pack_id, role)
                    VALUES (:k, 'loose', :p, true, true, :pk, CAST(:r AS pack_container_role))
                    RETURNING id
                    """
                ),
                {"k": key, "p": key.split(":", 1)[1], "pk": pack_id, "r": role},
            ).scalar_one()
        )
        n = conn.execute(
            text(
                "INSERT INTO pack_unit_sources (unit_id, source_file_id) "
                "SELECT :u, id FROM source_files WHERE path = ANY(CAST(:paths AS text[]))"
            ),
            {"u": uid, "paths": files},
        ).rowcount
    assert n == len(files)
    return uid


def _split_library(mat: MatEnv) -> dict[str, int]:
    """One loose_batch holding files of three folders, split across two packs + an orphan unit.
    No pack_containers row exists for the batch (it is split)."""
    mat.write("Alpha/body.stl", BODY)
    mat.write("Alpha/dup_body.stl", BODY)  # same bytes: dedupes to one blob
    mat.write("Alpha/Part.stl", PART_UP)
    mat.write("Alpha/part.stl", PART_LOW)  # case-insensitive clash with Part.stl
    mat.write("Alpha/preview.jpg", JPEG)
    mat.write("Beta/wing.stl", WING)
    mat.write("Beta/sub/tail.stl", TAIL)
    mat.write("Shared/common.stl", COMMON)  # a member of units of BOTH packs
    mat.write("Orphan/lost.stl", LOST)
    mat.catalog()
    assert (
        mat.scalar(
            "SELECT count(DISTINCT cf.container_id) FROM container_files cf "
            "JOIN containers c ON c.id = cf.container_id WHERE c.kind = 'loose_batch'"
        )
        == 1
    ), "fixture assumes a single loose_batch"
    alpha = mat.pack("Alpha", "Games", [])
    beta = mat.pack("Beta", "Terrain", [])
    _unit(
        mat,
        "loose:Alpha",
        ["Alpha/body.stl", "Alpha/dup_body.stl", "Alpha/Part.stl", "Alpha/part.stl"],
        pack_id=alpha,
        role="primary",
    )
    _unit(mat, "loose:AlphaPreview", ["Alpha/preview.jpg"], pack_id=alpha, role="absorbed")
    _unit(mat, "loose:SharedA", ["Shared/common.stl"], pack_id=alpha, role="source")
    _unit(mat, "loose:Beta", ["Beta/wing.stl", "Beta/sub/tail.stl"], pack_id=beta, role="primary")
    _unit(mat, "loose:SharedB", ["Shared/common.stl"], pack_id=beta, role="source")
    _unit(mat, "loose:Orphan", ["Orphan/lost.stl"])  # pack_id NULL, role NULL
    return {"alpha": alpha, "beta": beta}


def _files(mat: MatEnv, plan_id: int, pack_id: int) -> dict[str, dict]:
    return {
        r["rel_path"]: r
        for r in mat.rows(
            "SELECT rel_path, sha256, size, kind, container_id, anchor_path, member_chain "
            "FROM materialize_files WHERE plan_id = :p AND pack_id = :k",
            p=plan_id,
            k=pack_id,
        )
    }


def test_split_loose_batch_files_land_in_their_packs(mat) -> None:
    packs = _split_library(mat)
    res = mat.plan()
    t = res.totals

    dirs = {r["pack_id"]: r["dir"] for r in mat.rows("SELECT pack_id, dir FROM materialize_packs")}
    assert dirs == {packs["alpha"]: "Games/Alpha", packs["beta"]: "Terrain/Beta"}

    part_low = f"Alpha/part~{sha(PART_LOW)[:8]}.stl"  # collision naming, same rules as archives
    alpha = _files(mat, res.plan_id, packs["alpha"])
    assert sorted(alpha) == sorted(
        ["Alpha/body.stl", "Alpha/Part.stl", part_low, "Alpha/preview.jpg", "Shared/common.stl"]
    )
    assert alpha["Alpha/body.stl"]["sha256"] == sha(BODY)  # dup_body.stl deduped away
    assert alpha["Alpha/preview.jpg"]["kind"] == "image"  # absorbed-role unit is planned too
    assert alpha[part_low]["sha256"] == sha(PART_LOW)

    beta = _files(mat, res.plan_id, packs["beta"])
    assert sorted(beta) == ["Beta/sub/tail.stl", "Beta/wing.stl", "Shared/common.stl"]
    assert beta["Beta/wing.stl"]["sha256"] == sha(WING)

    # nothing from another pack's folder or the orphan leaks in
    every = {*alpha, *beta}
    assert not any("Orphan" in p or "lost" in p for p in every)
    assert not any(f["sha256"] == sha(LOST) for f in [*alpha.values(), *beta.values()])
    assert "Beta/wing.stl" not in alpha and "Alpha/body.stl" not in beta

    # provenance points at the loose batch + the exact source path
    batch = mat.container_of("Alpha/body.stl")
    assert alpha["Alpha/body.stl"]["container_id"] == batch
    assert alpha["Alpha/body.stl"]["anchor_path"] == "Alpha/body.stl"
    assert list(alpha["Alpha/body.stl"]["member_chain"]) == ["Alpha/body.stl"]

    assert t["packs"] == 2
    assert t["files"] == 8
    assert t["blobs"] == 7  # body(=dup_body), Part, part, preview, wing, tail, common
    assert t["missing_blobs"] == 0
    assert t["loose_blobs"] == 7 and t["archive_blobs"] == 0
    assert t["write_bytes_hardlink_mode"] == 0  # all hardlinks, zero bytes written


def test_file_in_two_packs_units_is_planned_in_both_with_one_blob(mat) -> None:
    packs = _split_library(mat)
    res = mat.plan()
    a = _files(mat, res.plan_id, packs["alpha"])["Shared/common.stl"]
    b = _files(mat, res.plan_id, packs["beta"])["Shared/common.stl"]
    assert a["sha256"] == b["sha256"] == sha(COMMON)
    blobs = mat.rows(
        "SELECT source_kind, source_path FROM materialize_blobs WHERE plan_id = :p AND sha256 = :s",
        p=res.plan_id,
        s=sha(COMMON),
    )
    assert blobs == [{"source_kind": "loose", "source_path": "Shared/common.stl"}]
    # the blob source for the duplicated-bytes pair is the lexicographically first path
    src = mat.scalar(
        "SELECT source_path FROM materialize_blobs WHERE plan_id = :p AND sha256 = :s",
        p=res.plan_id,
        s=sha(BODY),
    )
    assert src == "Alpha/body.stl"


def test_unit_without_pack_is_skipped_and_reported(mat) -> None:
    _split_library(mat)
    res = mat.plan()
    t = res.totals
    assert t["unassigned_loose_units"] == 1
    assert t["unassigned_loose_files"] == 1
    assert t["unassigned_loose_unit_sample"] == ["loose:Orphan"]
    assert (
        mat.scalar(
            "SELECT count(*) FROM materialize_files WHERE plan_id = :p AND sha256 = :s",
            p=res.plan_id,
            s=sha(LOST),
        )
        == 0
    )
    assert (
        mat.scalar(
            "SELECT count(*) FROM materialize_blobs WHERE plan_id = :p AND sha256 = :s",
            p=res.plan_id,
            s=sha(LOST),
        )
        == 0
    )
    # the persisted plan carries the same report
    stored = mat.scalar("SELECT totals->>'unassigned_loose_units' FROM materialize_plans")
    assert stored == "1"


def test_unit_pack_meta_lists_loose_units(mat) -> None:
    packs = _split_library(mat)
    res = mat.plan()
    meta = next(p.meta for p in res.packs if p.pack_id == packs["alpha"])
    units = {u["unit_key"]: u["role"] for u in meta["loose_units"]}
    assert units == {
        "loose:Alpha": "primary",
        "loose:AlphaPreview": "absorbed",
        "loose:SharedA": "source",
    }
    assert meta["containers"] == []


def test_batch_in_pack_containers_is_not_double_planned(mat) -> None:
    """A batch attached whole via pack_containers AND named by that pack's unit sources: each file
    is reached once (through the container, with the container's role)."""
    from forge.materialize.plan import _ROOTS, _SCOPE, KINDS

    mat.write("Alpha/body.stl", BODY)
    mat.write("Alpha/Part.stl", PART_UP)
    mat.catalog()
    batch = mat.container_of("Alpha/body.stl")
    pid = mat.pack("Gamma", "Games", [(batch, "absorbed")])
    _unit(mat, "loose:Alpha", ["Alpha/body.stl", "Alpha/Part.stl"], pack_id=pid, role="primary")

    with mat.engine.begin() as conn:
        for stmt in _ROOTS.strip().split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
        rows = conn.execute(text(_SCOPE), {"packs": [pid], "kinds": list(KINDS)}).mappings().all()
    assert len(rows) == 2  # not 4: the unit branch skips a batch already in pack_containers
    assert {r["role"] for r in rows} == {"absorbed"}

    res = mat.plan()
    files = _files(mat, res.plan_id, pid)
    assert sorted(files) == ["body.stl", "Part.stl"]
    assert res.totals["files"] == 2 and res.totals["blobs"] == 2


def test_unit_files_of_a_split_batch_do_not_pull_the_whole_batch(mat) -> None:
    """The same batch also holds Beta's files; Alpha's units must not pick them up."""
    packs = _split_library(mat)
    res = mat.plan()
    alpha = _files(mat, res.plan_id, packs["alpha"])
    assert all(f["container_id"] == mat.container_of("Alpha/body.stl") for f in alpha.values())
    assert sha(WING) not in {f["sha256"] for f in alpha.values()}


def test_pack_filter_and_non_present_unit_ignored(mat) -> None:
    packs = _split_library(mat)
    # a unit marked not present (source gone from the catalog's view) is ignored
    mat.execute("UPDATE pack_units SET present = false WHERE unit_key = 'loose:AlphaPreview'")
    res = mat.plan(pack_ids=[packs["alpha"]])
    assert res.totals["packs"] == 1
    alpha = _files(mat, res.plan_id, packs["alpha"])
    assert "Alpha/preview.jpg" not in alpha
    assert "Shared/common.stl" in alpha


def test_plan_is_deterministic(mat) -> None:
    _split_library(mat)

    def snapshot(plan_id: int) -> list:
        return [
            (r["pack_id"], r["rel_path"], r["sha256"], r["kind"], r["container_id"])
            for r in mat.rows(
                "SELECT pack_id, rel_path, sha256, kind, container_id FROM materialize_files "
                "WHERE plan_id = :p ORDER BY pack_id, rel_path",
                p=plan_id,
            )
        ]

    a = mat.plan()
    b = mat.plan()
    assert a.plan_id != b.plan_id
    assert snapshot(a.plan_id) == snapshot(b.plan_id)
    assert len(snapshot(a.plan_id)) == 8
    strip = {"plan_id"}
    assert {k: v for k, v in a.totals.items() if k not in strip} == {
        k: v for k, v in b.totals.items() if k not in strip
    }
    assert [(p.pack_id, p.dir, [f.rel_path for f in p.files]) for p in a.packs] == [
        (p.pack_id, p.dir, [f.rel_path for f in p.files]) for p in b.packs
    ]


def test_apply_links_split_batch_files_from_source(mat) -> None:
    _split_library(mat)
    mat.plan()
    before = mat.source_snapshot()
    assert mat.apply() == 0
    assert mat.source_snapshot() == before  # bytes/size/mtime/mode unchanged
    r = mat.verify(full=True)
    assert r["ok"], r

    alpha_body = mat.v2 / "Games/Alpha/Alpha/body.stl"
    assert alpha_body.read_bytes() == BODY
    assert alpha_body.stat().st_ino == (mat.src / "Alpha/body.stl").stat().st_ino
    a_common = mat.v2 / "Games/Alpha/Shared/common.stl"
    b_common = mat.v2 / "Terrain/Beta/Shared/common.stl"
    src_common = (mat.src / "Shared/common.stl").stat().st_ino
    assert a_common.stat().st_ino == b_common.stat().st_ino == src_common
    assert (mat.v2 / "Terrain/Beta/Beta/sub/tail.stl").read_bytes() == TAIL
    # the orphan file never reached v2
    assert not list(mat.v2.rglob(sha(LOST)))
    assert not list(mat.v2.rglob("lost.stl"))
