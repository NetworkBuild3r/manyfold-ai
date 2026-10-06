"""ASMT-018 pair, nested chain, reclaimable arithmetic, totals. INIT-032/SPEC-009."""

from __future__ import annotations

from tests.helpers import add_container, hex_sha
from tests.reports.helpers import add_archive_pack, add_loose_mesh, add_nested_mesh, add_source

from forge.db.enums import ContainerKind, ContainerStatus, FailureReason
from forge.reports.sql import collect_duplicates, collect_inventory
from forge.status import collect_status

# 3 shared + 1 unique each. Sizes chosen so totals are obvious by hand.
SHARED = (
    (b"stl-shared-a", "a.stl", 100, 10),
    (b"stl-shared-b", "b.stl", 200, 20),
    (b"stl-shared-c", "c.stl", 300, 30),
)
UNIQUE_A = (b"stl-only-alpha", "only-a.stl", 50, 5)
UNIQUE_B = (b"stl-only-beta", "only-b.stl", 70, 7)
ZIP_A = b"zip-bytes-alpha-pack-v1"
ZIP_B = b"zip-bytes-beta-pack-v2-different"


def _asmt018(session) -> None:
    add_archive_pack(session, "Games/alpha-pack.zip", ZIP_A, [*SHARED, UNIQUE_A])
    add_archive_pack(session, "Games/beta-pack.zip", ZIP_B, [*SHARED, UNIQUE_B])
    session.commit()


def test_asmt018_cross_pack_pair_and_archives_differ(session, engine) -> None:
    _asmt018(session)
    with engine.connect() as conn:
        doc = collect_duplicates(conn, min_copies=2, limit=0)
    assert doc["schema_version"] == 1
    assert len(doc["pairs"]) == 1
    pair = doc["pairs"][0]
    assert pair["shared_meshes"] == 3
    assert pair["containment_count"] == 0.75
    assert pair["meshes_a"] == 4
    assert pair["meshes_b"] == 4
    assert pair["archives_differ"] is True
    assert pair["archive_sha_a"] != pair["archive_sha_b"]
    assert pair["archive_sha_a"] == hex_sha(ZIP_A)
    assert pair["archive_sha_b"] == hex_sha(ZIP_B)
    assert {s["sha256"] for s in pair["shared"]} == {hex_sha(p) for p, _n, _s, _t in SHARED}
    assert pair["overlap_a"] == 0.75
    assert pair["overlap_b"] == 0.75
    blobs = {b["sha256"]: b for b in doc["blobs"]}
    assert set(blobs) == {hex_sha(p) for p, _n, _s, _t in SHARED}
    for payload, name, size, triangles in SHARED:
        row = blobs[hex_sha(payload)]
        assert row["copies"] == 2
        assert row["size"] == size
        assert row["triangles"] == triangles
        assert any(name in src for src in row["sources"])


def test_fixture_totals_match_hand_computed(session, engine) -> None:
    _asmt018(session)
    with engine.connect() as conn:
        inv = collect_inventory(conn)
        dups = collect_duplicates(conn, min_copies=2, limit=0)
    # 5 meshes + 2 archive blobs
    assert inv["summary"]["blobs"] == 7
    assert inv["summary"]["occurrences"] == 8
    assert inv["have"]["unique_meshes"] == 5
    assert inv["have"]["unique_mesh_bytes"] == 100 + 200 + 300 + 50 + 70
    assert inv["have"]["mesh_occurrences"] == 8
    assert inv["have"]["unique_bytes"] == 720 + len(ZIP_A) + len(ZIP_B)
    assert inv["have"]["occurrence_bytes"] == (100 + 200 + 300 + 50) + (100 + 200 + 300 + 70)
    assert inv["have"]["duplicate_ratio"] == 0.375
    assert dups["have"]["reclaimable_bytes"] == 100 + 200 + 300
    assert dups["summary"]["cross_pack_blobs"] == 3
    assert inv["asmt018"]["archived_mesh_members_hashed_before"] == 0
    assert inv["asmt018"]["archived_mesh_members_hashed_now"] == 8


def test_nested_archive_chain_render(session, engine) -> None:
    mesh = b"nested-hero-stl"
    add_nested_mesh(
        session,
        "D&D/Pack.rar",
        b"outer-rar-bytes",
        "inner.zip",
        b"inner-zip-bytes",
        mesh,
        "model.stl",
        size=111,
        triangles=99,
    )
    add_archive_pack(
        session,
        "D&D/Other.zip",
        b"other-zip-bytes",
        [(mesh, "model.stl", 111, 99)],
    )
    session.commit()
    with engine.connect() as conn:
        doc = collect_duplicates(conn, min_copies=2, limit=0)
    assert len(doc["blobs"]) == 1
    sources = doc["blobs"][0]["sources"]
    assert "Pack.rar > inner.zip > model.stl" in sources
    assert any(s.endswith("model.stl") and "Other.zip" in s for s in sources)


def test_reclaimable_bytes_three_packs(session, engine) -> None:
    payload = b"commons-mesh"
    add_archive_pack(session, "Anime/a.zip", b"za", [(payload, "x.stl", 1000, 1)])
    add_archive_pack(session, "Anime/b.zip", b"zb", [(payload, "x.stl", 1000, 1)])
    add_archive_pack(session, "Anime/c.zip", b"zc", [(payload, "x.stl", 1000, 1)])
    session.commit()
    with engine.connect() as conn:
        doc = collect_duplicates(conn, min_copies=2, limit=0)
    assert doc["blobs"][0]["copies"] == 3
    assert doc["blobs"][0]["reclaimable_bytes"] == 2000
    assert doc["have"]["reclaimable_bytes"] == 2000


def test_loose_folder_is_a_pack(session, engine) -> None:
    payload = b"loose-twin"
    add_loose_mesh(session, "Games/HeroA/mini.stl", payload, size=80, triangles=8)
    add_loose_mesh(session, "Games/HeroB/mini.stl", payload, size=80, triangles=8)
    session.commit()
    with engine.connect() as conn:
        doc = collect_duplicates(conn, min_copies=2, limit=0)
    assert doc["blobs"][0]["copies"] == 2
    packs = {p["pack_a"] for p in doc["pairs"]} | {p["pack_b"] for p in doc["pairs"]}
    assert "Games/HeroA" in packs
    assert "Games/HeroB" in packs


def test_same_pack_two_copies_is_not_cross_pack(session, engine) -> None:
    payload = b"twice-in-one-zip"
    add_archive_pack(
        session,
        "Tools/one.zip",
        b"one-zip",
        [(payload, "a.stl", 10, 1), (payload, "copy/a.stl", 10, 1)],
    )
    session.commit()
    with engine.connect() as conn:
        doc = collect_duplicates(conn, min_copies=2, limit=0)
    assert doc["blobs"] == []
    assert doc["pairs"] == []


def test_limit_and_min_copies(session, engine) -> None:
    members = [(b"m1", "1.stl", 10, 1), (b"m2", "2.stl", 20, 1)]
    add_archive_pack(session, "Misc/a.zip", b"za", members)
    add_archive_pack(session, "Misc/b.zip", b"zb", members)
    session.commit()
    with engine.connect() as conn:
        capped = collect_duplicates(conn, min_copies=2, limit=1)
        high = collect_duplicates(conn, min_copies=3, limit=0)
    assert len(capped["blobs"]) == 1
    assert high["blobs"] == []


def test_deterministic_blob_and_pair_order(session, engine) -> None:
    add_archive_pack(session, "DC/z-last.zip", b"zl", [(b"dup", "d.stl", 9, 1)])
    add_archive_pack(session, "DC/a-first.zip", b"za", [(b"dup", "d.stl", 9, 1)])
    session.commit()
    with engine.connect() as conn:
        doc = collect_duplicates(conn, min_copies=2, limit=0)
    pair = doc["pairs"][0]
    assert pair["pack_a"] < pair["pack_b"]
    assert pair["pack_a"] == "DC/a-first.zip"


def test_failed_count_matches_status(session, engine) -> None:
    src = add_source(session, "Games/broken.rar", fmt="rar")
    add_container(
        session,
        kind=ContainerKind.archive,
        format="rar",
        status=ContainerStatus.failed,
        failure_reason=FailureReason.reader_error,
        source_file_id=src.id,
    )
    session.commit()
    with engine.connect() as conn:
        inv = collect_inventory(conn)
    snap = collect_status(engine)
    assert inv["summary"]["failed_containers"] == sum(f["count"] for f in snap["failures"])
    assert sum(f["count"] for f in inv["failures"]) == inv["summary"]["failed_containers"]
    assert inv["failed_containers"][0]["path"] == "Games/broken.rar"
    assert inv["failed_containers"][0]["reason"] == "reader_error"


def test_source_tag_and_folder(session, engine) -> None:
    add_source(session, "AnySTL/foo/bar.zip", size=5, fmt="zip")
    add_source(session, "Games/hero.zip", size=7, fmt="zip")
    session.commit()
    with engine.connect() as conn:
        inv = collect_inventory(conn)
    folders = {r["folder"]: r for r in inv["by_top_level_folder"]}
    assert folders["AnySTL"]["files"] == 1
    assert folders["Games"]["files"] == 1
    tags = {r["tag"]: r for r in inv["by_source_tag"]}
    assert tags["AnySTL"]["files"] == 1
    assert tags[""]["files"] == 1
