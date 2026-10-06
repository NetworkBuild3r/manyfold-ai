"""``forge requeue`` and superseded-volume accounting. INIT-032/SPEC-007."""

from __future__ import annotations

from sqlalchemy import text

from forge.cli import main
from forge.packs.units import ContainerRow, SourceRow, plan_units
from forge.requeue import requeue
from forge.status import collect_status

SHA = "cd" * 32


def _source(conn, path: str, size: int) -> int:
    return int(
        conn.execute(
            text(
                "INSERT INTO source_files (path, size, mtime, kind) "
                "VALUES (:p, :s, now(), 'archive') RETURNING id"
            ),
            {"p": path, "s": size},
        ).scalar_one()
    )


def _container(conn, sid: int | None, *, status: str, reason: str | None = None, **kw) -> int:
    cid = int(
        conn.execute(
            text(
                "INSERT INTO containers (source_file_id, kind, format, depth, status, "
                "failure_reason, parent_container_id, members, bytes_read, source_bytes) "
                "VALUES (:s, CAST(:k AS container_kind), 'zip', :d, "
                "CAST(:st AS container_status), CAST(:r AS failure_reason), :p, 2, 10, 5) "
                "RETURNING id"
            ),
            {
                "s": sid,
                "k": kw.get("kind", "archive"),
                "d": kw.get("depth", 1),
                "st": status,
                "r": reason,
                "p": kw.get("parent"),
            },
        ).scalar_one()
    )
    if sid is not None and kw.get("kind", "archive") == "archive":
        conn.execute(text("INSERT INTO container_files VALUES (:c, :s, 1)"), {"c": cid, "s": sid})
    return cid


def _occurrence(conn, cid: int) -> None:
    conn.execute(
        text(
            "INSERT INTO blobs (sha256, size, kind) VALUES (:h, 1, 'other') ON CONFLICT DO NOTHING"
        ),
        {"h": SHA},
    )
    conn.execute(
        text(
            "INSERT INTO occurrences (blob_sha, container_id, member_chain, member_path, depth) "
            "VALUES (:h, :c, ARRAY['a.bin'], 'a.bin', 1)"
        ),
        {"h": SHA, "c": cid},
    )


def _status(conn, cid: int) -> tuple:
    return tuple(
        conn.execute(
            text(
                "SELECT status::text, failure_reason::text, attempts, members, source_bytes "
                "FROM containers WHERE id = :c"
            ),
            {"c": cid},
        ).one()
    )


def test_requeue_resets_top_level_and_nested_roots(engine, session) -> None:
    with engine.begin() as conn:
        big = _container(conn, _source(conn, "a/big.zip", 3000), status="failed", reason="oom")
        spool_root = _container(conn, _source(conn, "a/outer.zip", 100), status="done")
        nested = _container(
            conn,
            None,
            status="failed",
            reason="spool_exceeded",
            kind="nested",
            depth=2,
            parent=spool_root,
        )
        _occurrence(conn, spool_root)
        keep = _container(
            conn, _source(conn, "a/bad.zip", 50), status="failed", reason="reader_error"
        )
        enc = _container(conn, _source(conn, "a/enc.zip", 50), status="failed", reason="encrypted")

        res = requeue(conn, ("oom", "spool_exceeded"), dry_run=True)
        assert (res.selected, res.source_bytes, res.dry_run) == (2, 3100, True)
        assert _status(conn, big)[0] == "failed"  # dry run changes nothing

        res = requeue(conn, ("oom", "spool_exceeded"), max_source_bytes=1000)
        assert res.selected == 1 and res.skipped_too_big == 1 and res.ids == [spool_root]
        # the root is pending again, its occurrences and the failed child are gone
        assert _status(conn, spool_root) == ("pending", None, 0, 0, None)
        assert (
            conn.execute(
                text("SELECT count(*) FROM containers WHERE id = :n"), {"n": nested}
            ).scalar_one()
            == 0
        )
        assert conn.execute(text("SELECT count(*) FROM occurrences")).scalar_one() == 0
        # untouched: too big for the cap, other reasons
        assert _status(conn, big)[:2] == ("failed", "oom")
        assert _status(conn, keep)[:2] == ("failed", "reader_error")
        assert _status(conn, enc)[:2] == ("failed", "encrypted")

        res = requeue(conn, ("oom",))
        assert res.ids == [big] and _status(conn, big)[0] == "pending"


def test_requeue_cli_requires_a_reason(capsys) -> None:
    assert main(["requeue"]) == 2
    assert "--reason" in capsys.readouterr().err


def test_superseded_volumes_are_not_counted_or_units(engine, session) -> None:
    with engine.begin() as conn:
        one = _container(conn, _source(conn, "p/x.part1/x.part1.rar", 10), status="pending")
        two = _container(conn, None, status="done")
        three = _container(conn, None, status="done")
        conn.execute(
            text(
                "UPDATE containers SET superseded_by_id = :o, source_bytes = NULL, members = 0 "
                "WHERE id = ANY(:ids)"
            ),
            {"o": one, "ids": [two, three]},
        )
    snap = collect_status(engine)
    rows = {(r["kind"], r["status"]): r["count"] for r in snap["containers"]}
    assert rows == {("archive", "pending"): 1}  # superseded rows are not archive/done
    assert snap["superseded_volumes"] == 2


def test_plan_units_skips_superseded_volumes() -> None:
    sources = [SourceRow(1, "p/x.part1.rar", "archive"), SourceRow(2, "p/x.part2.rar", "archive")]
    containers = [
        ContainerRow(10, "archive", 1, None, "done"),
        ContainerRow(11, "archive", 2, None, "done", superseded_by_id=10),
    ]
    units = plan_units(sources, containers, [(10, 1), (10, 2)])
    assert [u.key for u in units] == ["archive:p/x.part1.rar"]
    assert units[0].source_file_ids == [1, 2]
