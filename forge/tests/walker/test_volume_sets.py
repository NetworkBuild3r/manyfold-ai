"""Multi-volume sets resolved across sibling ``<name>.partN/`` folders. INIT-032/SPEC-007.

The old spark-curate layout put each volume in its own folder (``Naruto.part3/Naruto.part3.rar``).
The walker must see those as ONE container whose files are every volume in order; the volumes
that were catalogued alone before are retired (``superseded_by_id``), never double counted.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import text
from tests.walker.conftest import RAR5_MAGIC

from forge.db.enums import SourceFileKind
from forge.walker import WalkFile, group_archive_sets, rar_volume_flag, run

SHA = "ab" * 32
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "engine"


def wf(path: str, fmt: str | None = "rar5", *, vol: bool | None = None, size: int = 100):
    return WalkFile(path, size, 0, SourceFileKind.archive, fmt, rar_volume=vol)


def sets(files):
    _all, groups = group_archive_sets(files)
    return [g for g in groups if g.volume_set]


def paths(group) -> list[str]:
    return [f.path for f in group.files]


# ----------------------------------------------------------------------------- name resolution


def test_each_volume_in_its_own_part_folder_is_one_set() -> None:
    files = [
        wf(f"Anime/Naruto/Naruto.part{n}/Naruto.part{n}.rar") for n in (3, 1, 2, 10, 4, 5, 6, 7)
    ] + [wf(f"Anime/Naruto/Naruto.part{n}/Naruto.part{n}.rar") for n in (8, 9)]
    (group,) = sets(files)
    assert group.volume_set == "Anime/Naruto/Naruto|part"
    assert [int(p.rsplit("part", 1)[1].split(".")[0]) for p in paths(group)] == list(range(1, 11))
    assert not group.missing_volume and group.missing == ()
    assert [f.volume_ordinal for f in group.files] == list(range(1, 11))
    assert group.format == "rar5"


def test_first_volume_in_the_bare_set_folder_joins_the_part_folders() -> None:
    files = [
        wf("Anime/Naruto/Naruto.part1.rar"),
        wf("Anime/Naruto.part2/Naruto.part2.rar"),
        wf("Anime/Naruto.part3/Naruto.part3.rar"),
    ]
    (group,) = sets(files)
    assert paths(group) == [f.path for f in files]
    assert not group.missing_volume


def test_space_separated_folder_token_and_zero_padding() -> None:
    files = [
        wf("DC/Harley Quinn part1/Harley Quinn.part01.rar"),
        wf("DC/Harley Quinn part2/Harley Quinn.part02.rar"),
        wf("DC/Harley Quinn part3/Harley Quinn.part03.rar"),
    ]
    (group,) = sets(files)
    assert len(group.files) == 3 and not group.missing_volume
    assert group.volume_set == "DC/Harley Quinn|part"


def test_same_folder_set_still_works_and_folder_must_be_the_files_own() -> None:
    files = [wf(f"Pack/Skies - Minis.part{n:02d}.rar") for n in (1, 2, 3)]
    (group,) = sets(files)
    assert group.volume_set == "Pack/Skies - Minis|part"
    # Two different sets that share a parent folder stay two sets.
    files += [wf(f"Pack/Skies - Ships.part{n:02d}.rar") for n in (1, 2)]
    assert len(sets(files)) == 2


def test_other_folders_other_sets_and_copies_do_not_merge() -> None:
    files = [
        wf("A/Naruto.part1/Naruto.part1.rar"),
        wf("A/Naruto.part2/Naruto.part2.rar"),
        wf("B/Naruto.part1/Naruto.part1.rar"),
        wf("B/Naruto.part2/Naruto.part2.rar"),
    ]
    found = sets(files)
    assert sorted(g.volume_set for g in found) == ["A/Naruto|part", "B/Naruto|part"]
    assert all(len(g.files) == 2 and not g.missing_volume for g in found)


def test_different_format_volumes_do_not_merge() -> None:
    files = [
        wf("A/X.part1/X.part1.rar", "rar4"),
        wf("A/X.part2/X.part2.rar", "rar5"),
    ]
    found = sets(files)
    # one volume each: part1 is a one-volume archive, part2 is a lone continuation
    assert [g.missing for g in found] == [(1,)]


def test_gap_is_missing_volume_with_the_numbers() -> None:
    files = [wf(f"A/X.part{n}/X.part{n}.rar") for n in (1, 2, 5, 6)]
    (group,) = sets(files)
    assert group.missing_volume and group.missing == (3, 4)
    assert len(group.files) == 4


def test_lone_continuation_is_missing_volume_and_lone_part1_is_an_archive() -> None:
    (lone,) = sets([wf("A/X.part3/X.part3.rar")])
    assert lone.missing_volume and lone.missing == (1, 2)
    assert len(lone.files) == 1
    _all, groups = group_archive_sets([wf("A/Y.part1/Y.part1.rar")])
    assert [(g.volume_set, g.missing_volume, len(g.files)) for g in groups] == [(None, False, 1)]


def test_set_without_volume_one_is_missing_one() -> None:
    files = [wf(f"A/X.part{n}/X.part{n}.rar") for n in (2, 3)]
    (group,) = sets(files)
    assert group.missing == (1,)


def test_duplicate_volume_number_is_not_a_complete_set() -> None:
    files = [
        wf("A/X.part1/X.part1.rar"),
        wf("A/X.part2/X.part2.rar"),
        wf("A/X.part2 (2)/X.part2.rar"),
    ]
    found = sets(files)
    assert any(g.missing_volume for g in found)


# --------------------------------------------------------------- loose spelling needs evidence


def test_loose_part_spelling_needs_the_rar_volume_flag() -> None:
    names = [f"Loot/LS_Crimson_part{n}/LS_Crimson_part{n}.rar" for n in (1, 2, 3)]
    # independent archives that merely end in a number: untouched
    assert sets([wf(p, vol=False) for p in names]) == []
    assert sets([wf(p, vol=None) for p in names]) == []
    (group,) = sets([wf(p, vol=True) for p in names])
    assert len(group.files) == 3 and not group.missing_volume
    assert group.volume_set.endswith("|partx")


def test_loose_spelling_with_text_after_the_number() -> None:
    files = [wf(f"K/kraken.part{n} lord/kraken.part{n} lord.rar", vol=True) for n in (1, 2, 3)]
    (group,) = sets(files)
    assert len(group.files) == 3 and not group.missing_volume


def test_rar_volume_flag_reads_real_headers() -> None:
    def flag(name: str) -> bool | None:
        return rar_volume_flag((FIXTURES / name).read_bytes()[:64])

    for vol in ("split_rar5.part1.rar", "split_rar5.part3.rar", "split_rar4.rar"):
        assert flag(vol) is True, vol
    assert flag("split_rar4.r01") is True
    for single in ("basic_rar5_solid.rar", "basic_rar4.rar", "depth3.rar"):
        assert flag(single) is False, single
    assert rar_volume_flag(b"PK\x03\x04" + b"\0" * 60) is None
    assert rar_volume_flag(RAR5_MAGIC) is None  # truncated header


# ----------------------------------------------------- the other schemes get typed missing too


def test_split_zip_without_its_closing_zip_is_missing_the_lead() -> None:
    files = [wf("Z/Tanis.z01", "zip"), wf("Z/Tanis.z02", "zip")]
    (group,) = sets(files)
    assert group.missing_volume and group.missing == ("lead",)
    files.append(wf("Z/Tanis.zip", "zip"))
    (group,) = sets(files)
    assert not group.missing_volume and len(group.files) == 3


def test_dotted_rar_without_its_lead_is_missing() -> None:
    (group,) = sets([wf("R/x.r00", "rar4"), wf("R/x.r01", "rar4")])
    assert group.missing == ("lead",)
    (group,) = sets([wf("R/x.rar", "rar4"), wf("R/x.r00", "rar4"), wf("R/x.r01", "rar4")])
    assert not group.missing_volume and len(group.files) == 3


def test_nnn_gap_lists_the_numbers() -> None:
    files = [wf("S/a.7z.001", "7z"), wf("S/a.7z.004", "7z")]
    (group,) = sets(files)
    assert group.missing == (2, 3)


# ----------------------------------------------------------------------- DB: sync / supersede


def _tree(root: Path) -> None:
    for n in (1, 2, 3):
        d = root / "Lib" / "Ruins" / f"Ruins.part{n}"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"Ruins.part{n}.rar").write_bytes(RAR5_MAGIC + bytes([n]) * (10 * n))
    gap = root / "Lib" / "Gap"
    for n in (1, 4):
        d = gap / f"Gap.part{n}"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"Gap.part{n}.rar").write_bytes(RAR5_MAGIC + bytes([n]))


def _archive_containers(session) -> list[dict]:
    rows = session.execute(
        text(
            """
            SELECT c.id, c.status::text AS status, c.failure_reason::text AS reason,
                   c.superseded_by_id, c.notes, c.source_file_id,
                   (SELECT array_agg(sf.path ORDER BY cf.ordinal) FROM container_files cf
                    JOIN source_files sf ON sf.id = cf.source_file_id
                    WHERE cf.container_id = c.id) AS paths
            FROM containers c WHERE c.kind = 'archive' ORDER BY c.id
            """
        )
    ).mappings()
    return [dict(r) for r in rows]


def test_walk_seeds_one_container_per_cross_folder_set(tmp_path: Path, session) -> None:
    _tree(tmp_path)
    run(source_root=tmp_path, threads=2)
    rows = _archive_containers(session)
    assert len(rows) == 2
    ruins = next(r for r in rows if "Ruins" in r["paths"][0])
    assert ruins["status"] == "pending"
    assert ruins["paths"] == [f"Lib/Ruins/Ruins.part{n}/Ruins.part{n}.rar" for n in (1, 2, 3)]
    first = session.execute(
        text("SELECT path FROM source_files WHERE id = :i"), {"i": ruins["source_file_id"]}
    ).scalar_one()
    assert first == ruins["paths"][0]
    assert json.loads(ruins["notes"]) == {"volume_set": "Lib/Ruins/Ruins|part", "volumes": 3}
    gap = next(r for r in rows if "Gap" in r["paths"][0])
    assert (gap["status"], gap["reason"]) == ("failed", "missing_volume")
    assert json.loads(gap["notes"])["missing_volumes"] == [2, 3]


def _legacy_split(
    session, set_prefix: str, *, statuses: list[str], reverse: bool = False
) -> list[int]:
    """Re-create the old per-volume catalogue: one container per volume file, each with an
    occurrence, as the sweep left them before the set was resolved."""
    session.execute(text("DELETE FROM occurrences"))
    session.execute(
        text(
            "DELETE FROM container_files WHERE container_id IN "
            "(SELECT c.id FROM containers c JOIN container_files cf ON cf.container_id = c.id "
            " JOIN source_files sf ON sf.id = cf.source_file_id WHERE sf.path LIKE :p)"
        ),
        {"p": set_prefix + "%"},
    )
    session.execute(
        text(
            "DELETE FROM containers WHERE kind = 'archive' AND id NOT IN "
            "(SELECT container_id FROM container_files)"
        ),
        {},
    )
    ids = list(
        session.execute(
            text("SELECT id FROM source_files WHERE path LIKE :p ORDER BY path"),
            {"p": set_prefix + "%"},
        ).scalars()
    )
    if reverse:
        ids.reverse()
    out = []
    session.execute(
        text(
            "INSERT INTO blobs (sha256, size, kind) VALUES ('" + SHA + "', 1, 'other') "
            "ON CONFLICT DO NOTHING"
        )
    )
    for sid, status in zip(ids, statuses, strict=True):
        cid = session.execute(
            text(
                "INSERT INTO containers (source_file_id, kind, format, depth, status, "
                "failure_reason, members, bytes_read, source_bytes) VALUES (:s, 'archive', "
                "'rar5', 1, CAST(:st AS container_status), "
                "CASE WHEN :st = 'failed' THEN 'reader_error' END::failure_reason, 1, 5, 99) "
                "RETURNING id"
            ),
            {"s": sid, "st": status},
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO container_files (container_id, source_file_id, ordinal) "
                "VALUES (:c, :s, 1)"
            ),
            {"c": cid, "s": sid},
        )
        session.execute(
            text(
                "INSERT INTO occurrences (blob_sha, container_id, member_chain, member_path, "
                "depth) VALUES ('" + SHA + "', :c, ARRAY['m.bin'], 'm.bin', 1)"
            ),
            {"c": cid},
        )
        out.append(int(cid))
    session.commit()
    return out


def test_rewalk_merges_legacy_volume_containers_and_supersedes_the_rest(
    tmp_path: Path, session
) -> None:
    _tree(tmp_path)
    run(source_root=tmp_path, threads=2)
    legacy = _legacy_split(session, "Lib/Ruins/", statuses=["failed", "done", "failed"])

    result = run(source_root=tmp_path, threads=2)
    session.expire_all()
    assert result.counts.changed == 0 and result.counts.containers_seeded == 1

    rows = {r["id"]: r for r in _archive_containers(session)}
    keep, two, three = (rows[i] for i in legacy)
    # volume 1's container is the set container: pending, all volumes, nothing left over
    assert keep["status"] == "pending" and keep["reason"] is None
    assert keep["paths"] == [f"Lib/Ruins/Ruins.part{n}/Ruins.part{n}.rar" for n in (1, 2, 3)]
    assert keep["superseded_by_id"] is None
    assert json.loads(keep["notes"])["merged_containers"] == sorted([legacy[1], legacy[2]])
    # the others are retired, not failed, not deleted, with no files/occurrences/bytes
    for other in (two, three):
        assert other["status"] == "done" and other["reason"] is None
        assert other["superseded_by_id"] == keep["id"]
        assert other["paths"] is None
        assert json.loads(other["notes"])["superseded_by"] == keep["id"]
    assert (
        session.execute(
            text("SELECT count(*) FROM occurrences WHERE container_id = ANY(:ids)"),
            {"ids": legacy},
        ).scalar_one()
        == 0
    )
    assert (
        session.execute(
            text("SELECT count(source_bytes) FROM containers WHERE id = ANY(:ids)"),
            {"ids": legacy},
        ).scalar_one()
        == 0
    )

    # idempotent
    again = run(source_root=tmp_path, threads=2)
    assert again.counts.containers_seeded == 0


def test_rewalk_when_volume_one_is_not_the_lowest_container_id(tmp_path: Path, session) -> None:
    _tree(tmp_path)
    run(source_root=tmp_path, threads=2)
    # containers created in reverse volume order: volume 1 owns the HIGHEST id
    ids = _legacy_split(session, "Lib/Ruins/", statuses=["done"] * 3, reverse=True)
    run(source_root=tmp_path, threads=2)
    session.expire_all()
    rows = {r["id"]: r for r in _archive_containers(session)}
    owner = next(r for r in rows.values() if r["paths"] and len(r["paths"]) == 3)
    assert owner["id"] == ids[-1]
    first_path = session.execute(
        text("SELECT path FROM source_files WHERE id = :i"), {"i": owner["source_file_id"]}
    ).scalar_one()
    assert first_path.endswith("Ruins.part1/Ruins.part1.rar")
    assert sum(1 for r in rows.values() if r["superseded_by_id"] == owner["id"]) == 2


def test_lone_continuation_read_before_becomes_typed_missing_volume(
    tmp_path: Path, session
) -> None:
    d = tmp_path / "Lib" / "Solo.part2"
    d.mkdir(parents=True)
    (d / "Solo.part2.rar").write_bytes(RAR5_MAGIC + b"x")
    run(source_root=tmp_path, threads=2)
    # pretend an older walk/sweep had read it alone and called it done
    session.execute(
        text("UPDATE containers SET status = 'done', failure_reason = NULL, members = 3")
    )
    session.commit()
    run(source_root=tmp_path, threads=2)
    session.expire_all()
    (row,) = _archive_containers(session)
    assert (row["status"], row["reason"]) == ("failed", "missing_volume")
    assert json.loads(row["notes"])["missing_volumes"] == [1]


def test_unchanged_files_pick_up_new_volume_set_names(tmp_path: Path, session) -> None:
    _tree(tmp_path)
    run(source_root=tmp_path, threads=2)
    session.execute(text("UPDATE source_files SET volume_set = 'stale|part'"))
    session.commit()
    result = run(source_root=tmp_path, threads=2)
    session.expire_all()
    assert result.counts.changed == 0 and result.counts.containers_seeded == 0
    got = (
        session.execute(
            text("SELECT DISTINCT volume_set FROM source_files WHERE path LIKE 'Lib/Ruins/%'")
        )
        .scalars()
        .all()
    )
    assert got == ["Lib/Ruins/Ruins|part"]
