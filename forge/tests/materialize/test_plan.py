"""``forge materialize plan`` on a real (walker + sweep) catalog. INIT-032/SPEC-012."""

from __future__ import annotations

import json

from tests.materialize.conftest import SHARED, needs_native, sha

pytestmark = needs_native


def _files(mat, plan_id: int, pack_id: int) -> dict[str, dict]:
    return {
        r["rel_path"]: r
        for r in mat.rows(
            "SELECT rel_path, sha256, size, kind FROM materialize_files "
            "WHERE plan_id = :p AND pack_id = :k",
            p=plan_id,
            k=pack_id,
        )
    }


def test_plan_layout_dedup_and_sources(library) -> None:
    mat, packs = library
    res = mat.plan()
    t = res.totals
    assert t["packs"] == 3
    assert t["files"] == 17
    assert t["blobs"] == 14  # 3 shared STLs counted once
    assert t["missing_blobs"] == 0
    assert t["junk_blobs_skipped"] >= 1
    assert t["loose_blobs"] == 3  # hero_body, preview, shared1
    assert t["archive_blobs"] == 11
    assert t["linked_bytes"] - t["unique_bytes"] == t["dedup_saved_bytes"] > 0

    dirs = {r["pack_id"]: r["dir"] for r in mat.rows("SELECT pack_id, dir FROM materialize_packs")}
    assert dirs == {
        packs["hero"]: "Anime/Hero",
        packs["knight"]: "Games/Knight",
        packs["ruins"]: "Terrain/Ruins",
    }

    hero = _files(mat, res.plan_id, packs["hero"])
    assert sorted(hero) == [
        "docs/readme.txt",
        "extras/bonus/base.stl",
        "hero_body.stl",
        "parts/shared1.stl",
        "parts/shared2.stl",
        "parts/shared3.stl",
        "preview.jpg",
    ]
    assert not any("MACOSX" in p or "/._" in p for p in hero)
    knight = _files(mat, res.plan_id, packs["knight"])
    assert sorted(knight) == [f"stl/{n}" for n in ("knight.stl", *sorted(SHARED))]
    ruins = _files(mat, res.plan_id, packs["ruins"])
    assert sorted(ruins) == [
        "Ruins/empty.txt",
        "Ruins/images/preview.png",
        "Ruins/models/cube_ascii.stl",
        "Ruins/models/cube_binary.stl",
        "Ruins/readme.txt",
        "extras/notes.txt",
    ]
    for name, data in SHARED.items():
        assert hero[f"parts/{name}"]["sha256"] == knight[f"stl/{name}"]["sha256"] == sha(data)

    src = {
        r["sha256"]: r
        for r in mat.rows(
            "SELECT sha256, source_kind, source_path, member_chain, unit_id "
            "FROM materialize_blobs WHERE plan_id = :p",
            p=res.plan_id,
        )
    }
    assert src[sha(SHARED["shared1.stl"])]["source_kind"] == "loose"
    assert src[sha(SHARED["shared1.stl"])]["source_path"] == "Anime/Hero/shared1.stl"
    assert src[sha(SHARED["shared2.stl"])]["source_kind"] == "archive"
    base = hero["extras/bonus/base.stl"]["sha256"]
    assert src[base]["member_chain"] == ["extras.zip", "bonus/base.stl"]
    units = mat.rows("SELECT kind, count(*) AS n FROM materialize_units GROUP BY kind")
    by_kind = {u["kind"]: u["n"] for u in units}
    assert by_kind["loose"] == 1
    assert by_kind["archive"] >= 3  # Hero.zip/Knight.zip (shared), Ruins set, extras.rar


def test_plan_is_append_only_and_supersedes(library) -> None:
    mat, _ = library
    a = mat.plan()
    b = mat.plan()
    st = {r["id"]: r["status"] for r in mat.rows("SELECT id, status FROM materialize_plans")}
    assert st == {a.plan_id: "superseded", b.plan_id: "active"}


def test_plan_skips_provisional_unless_asked(library) -> None:
    mat, _ = library
    mat.pack(
        "Draft",
        None,
        [(mat.container_of("Games/Knight/Knight.zip"), "primary")],
        status="provisional",
    )
    assert mat.plan().totals["packs"] == 3
    t = mat.plan(include_provisional=True).totals
    assert t["packs"] == 4
    assert t["uncategorized_packs_in_misc"] == 1
    assert (
        mat.scalar(
            "SELECT dir FROM materialize_packs WHERE name = 'Draft' AND plan_id = "
            "(SELECT max(id) FROM materialize_plans)"
        )
        == "Misc/Draft"
    )


def test_duplicate_pack_names_get_distinct_folders(library) -> None:
    mat, _ = library
    pid = mat.pack("hero", "Anime", [(mat.container_of("Games/Knight/Knight.zip"), "primary")])
    mat.plan()
    d = mat.scalar("SELECT dir FROM materialize_packs WHERE pack_id = :p", p=pid)
    assert d == f"Anime/hero [{pid}]"


def test_shortage_is_reported(library) -> None:
    mat, packs = library
    mat.execute("UPDATE source_files SET present = false WHERE path = 'Games/Knight/Knight.zip'")
    res = mat.plan()
    assert res.totals["missing_blobs"] == 1  # knight.stl lives only in Knight.zip
    row = mat.rows(
        "SELECT source_kind, state, error FROM materialize_blobs WHERE source_kind = 'missing'"
    )[0]
    assert row == {"source_kind": "missing", "state": "missing", "error": "no_readable_source"}


def test_flat_layout(library) -> None:
    mat, packs = library
    res = mat.plan(layout="flat")
    hero = _files(mat, res.plan_id, packs["hero"])
    assert all("/" not in p for p in hero)
    assert "base.stl" in hero


def test_jsonl_export(library) -> None:
    from forge.materialize.plan import jsonl_lines

    mat, _ = library
    lines = [json.loads(x) for x in jsonl_lines(mat.plan())]
    assert lines[0]["type"] == "totals" and lines[0]["files"] == 17
    packs = [x for x in lines if x["type"] == "pack"]
    assert len(packs) == 3
    srcs = {f["source"]["kind"] for p in packs for f in p["files"]}
    assert srcs == {"loose", "archive"}


def test_plan_refuses_while_apply_holds_claims(library) -> None:
    from forge.materialize.plan import PlanError

    mat, _ = library
    mat.plan()
    mat.execute(
        "UPDATE materialize_units SET status = 'claimed', claimed_at = now() "
        "WHERE id = (SELECT min(id) FROM materialize_units)"
    )
    try:
        mat.plan()
    except PlanError as x:
        assert "in progress" in str(x)
    else:
        raise AssertionError("plan should refuse")
    mat.plan(force=True)
