"""SPEC-007 sweep runner: claim/resume, reaper, idempotency, nested rows, re-queue, status.

AC1 kill a worker mid-container -> pending after the stale window -> completes elsewhere, no dup.
AC2 4 concurrent workers x 100 containers -> each done exactly once.
"""

from __future__ import annotations

import io
import json
import multiprocessing as mp
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import pytest

from forge import sweep
from forge.engine import Result
from forge.status import collect_status, format_status, metrics_text, serve_metrics
from forge.sweep import (
    SweepSettings,
    claim_one,
    reap,
    register_worker,
    release_own_claims,
    worker_loop,
)
from tests.sweep import _proc
from tests.sweep.conftest import needs_native, sha

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "engine"


def _wait(pred, timeout: float = 30.0, step: float = 0.1):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = pred()
        if value:
            return value
        time.sleep(step)
    raise AssertionError("timed out waiting for condition")


def _container(env, cid: int):
    return env.rows("SELECT * FROM containers WHERE id = :cid", cid=cid)[0]


def _occ_paths(env, cid: int) -> list[str]:
    return [
        r["member_path"]
        for r in env.rows(
            "SELECT member_path FROM occurrences WHERE container_id = :cid ORDER BY 1", cid=cid
        )
    ]


def _run(env, worker_id: str = "t/p0", **kw):
    return worker_loop(worker_id, env.settings(), db_url=env.db_url, once=True, **kw)


# ------------------------------------------------------------------------------- basic loose


def test_loose_batch_hashes_every_file_with_relative_chain(sweep_env) -> None:
    files = {"Cat/Model/a.stl": b"solid a\nendsolid a\n", "Cat/Model/b.jpg": b"\xff\xd8\xffjpeg"}
    cid = sweep_env.seed_loose(files)
    stats = _run(sweep_env)
    assert stats.processed == [cid]
    row = _container(sweep_env, cid)
    assert row["status"] == "done" and row["failure_reason"] is None
    assert row["members"] == 2 and row["attempts"] == 1
    assert row["source_bytes"] == sum(len(v) for v in files.values())
    assert row["finished_at"] is not None
    occ = sweep_env.rows(
        "SELECT member_chain, blob_sha, depth FROM occurrences WHERE container_id = :c ORDER BY 1",
        c=cid,
    )
    assert [list(o["member_chain"]) for o in occ] == [[k] for k in sorted(files)]
    assert {o["blob_sha"] for o in occ} == {sha(v) for v in files.values()}
    assert all(o["depth"] == 0 for o in occ)
    blob = sweep_env.rows("SELECT * FROM blobs WHERE sha256 = :s", s=sha(files["Cat/Model/a.stl"]))
    assert blob[0]["ext"] == "stl" and blob[0]["kind"] == "mesh"


def test_reprocessing_never_duplicates_occurrences(sweep_env) -> None:
    files = {f"d/f{i}.stl": f"solid {i}".encode() for i in range(5)}
    cid = sweep_env.seed_loose(files)
    _run(sweep_env)
    with sweep_env.engine.begin() as conn:
        conn.exec_driver_sql(f"UPDATE containers SET status = 'pending' WHERE id = {cid}")
    _run(sweep_env)
    assert len(_occ_paths(sweep_env, cid)) == 5
    assert sweep_env.scalar("SELECT count(*) FROM occurrences") == 5
    assert _container(sweep_env, cid)["attempts"] == 2


# ---------------------------------------------------------------------------- AC2 concurrency


def test_ac2_four_workers_process_each_container_exactly_once(sweep_env) -> None:
    shared = b"solid shared\nendsolid shared\n"  # one blob every worker inserts concurrently
    ids = [
        sweep_env.seed_loose(
            {f"m{i:03d}/own.stl": f"solid {i}".encode(), f"m{i:03d}/s.stl": shared}
        )
        for i in range(100)
    ]
    ctx = mp.get_context("spawn")
    with ctx.Pool(4) as pool:
        results = pool.starmap(_proc.drain, [(f"ac2/p{i}", sweep_env.db_url) for i in range(4)])
    processed = [cid for r in results for cid in r]
    assert sorted(processed) == sorted(ids), "every container processed exactly once"
    assert sum(1 for r in results if r) >= 2, "work was actually spread over workers"
    rows = sweep_env.rows("SELECT status, attempts, count(*) AS n FROM containers GROUP BY 1, 2")
    assert [(r["status"], r["attempts"], r["n"]) for r in rows] == [("done", 1, 100)]
    assert sweep_env.scalar("SELECT count(*) FROM occurrences") == 200
    assert sweep_env.scalar("SELECT count(*) FROM blobs") == 101


# -------------------------------------------------------------------------- AC1 kill + resume


def test_ac1_killed_worker_container_returns_to_pending_and_completes_elsewhere(sweep_env) -> None:
    files = {f"k/f{i}.stl": f"solid kill {i}".encode() for i in range(3)}
    cid = sweep_env.seed_loose(files)
    ctx = mp.get_context("spawn")
    victim = ctx.Process(target=_proc.stall_worker, args=("victim/p0", sweep_env.db_url))
    victim.start()
    try:
        _wait(lambda: len(_occ_paths(sweep_env, cid)) >= 1)
        row = _container(sweep_env, cid)
        assert row["status"] == "claimed" and row["claimed_by"] == "victim/p0"
        os.kill(victim.pid, signal.SIGKILL)  # no cleanup: like an OOM-killed pod
        victim.join(10)
    finally:
        if victim.is_alive():
            victim.kill()
    assert _container(sweep_env, cid)["status"] == "claimed"

    started = time.monotonic()
    stats = _run(sweep_env, "rescuer/p0")
    assert time.monotonic() - started >= 1.0, "reclaimed only after the heartbeat went stale"
    assert stats.processed == [cid]
    row = _container(sweep_env, cid)
    assert row["status"] == "done" and row["claimed_by"] == "rescuer/p0"
    assert row["attempts"] == 2
    paths = _occ_paths(sweep_env, cid)
    assert paths == sorted(files), "partial first attempt purged, no duplicate occurrences"
    assert sweep_env.scalar("SELECT count(*) FROM occurrences") == 3


def test_sigterm_releases_in_flight_claim_without_counting_the_attempt(sweep_env) -> None:
    cid = sweep_env.seed_loose({"t/a.stl": b"solid t", "t/b.stl": b"solid u"})
    ctx = mp.get_context("spawn")
    child = ctx.Process(target=_proc.stall_child, args=("term/p0", sweep_env.db_url))
    child.start()
    try:
        _wait(lambda: len(_occ_paths(sweep_env, cid)) >= 1)
        os.kill(child.pid, signal.SIGTERM)
        child.join(30)
        assert child.exitcode == 0
    finally:
        if child.is_alive():
            child.kill()
    row = _container(sweep_env, cid)
    assert row["status"] == "pending" and row["claimed_by"] is None
    assert row["attempts"] == 0
    assert _occ_paths(sweep_env, cid) == []


# ---------------------------------------------------------------------------------- reaper


def _claimed(env, worker: str, attempts: int, age_seconds: int) -> int:
    cid = env.seed_loose({f"r/{worker}-{attempts}-{age_seconds}.stl": b"solid r"})
    with env.engine.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE containers SET status = 'claimed', claimed_by = %(w)s, attempts = %(a)s, "
            "claimed_at = now() - make_interval(secs => %(age)s) WHERE id = %(id)s",
            {"w": worker, "a": attempts, "age": age_seconds, "id": cid},
        )
    return cid


def test_reaper_stale_window_retries_and_exhaustion(sweep_env, monkeypatch) -> None:
    monkeypatch.setenv("FORGE_SWEEP_STALE_SECONDS", "3600")
    monkeypatch.setenv("FORGE_SWEEP_HEARTBEAT_STALE_SECONDS", "300")
    settings = SweepSettings.from_env()
    eng = sweep_env.engine
    register_worker(eng, "alive/p0", None)  # fresh heartbeat
    old_alive = _claimed(sweep_env, "alive/p0", 1, 7200)  # past the wall-cap window
    young_alive = _claimed(sweep_env, "alive/p0", 1, 10)  # in flight, healthy
    young_ghost = _claimed(sweep_env, "ghost/p0", 1, 10)  # no heartbeat, not yet stale
    old_ghost = _claimed(sweep_env, "ghost/p0", 2, 900)  # no heartbeat for > 300 s
    exhausted = _claimed(sweep_env, "ghost/p0", 3, 900)  # third attempt died
    with eng.begin() as conn:  # a stale partial occurrence must be purged on release
        conn.exec_driver_sql(
            "INSERT INTO blobs (sha256, size, kind) VALUES (%(s)s, 1, 'mesh')", {"s": "a" * 64}
        )
        conn.exec_driver_sql(
            "INSERT INTO occurrences (blob_sha, container_id, member_chain, member_path, depth) "
            "VALUES (%(s)s, %(c)s, ARRAY['x'], 'x', 0)",
            {"s": "a" * 64, "c": old_ghost},
        )

    counts = reap(eng, settings)
    assert (counts.released, counts.exhausted) == (2, 1)
    assert _container(sweep_env, old_alive)["status"] == "pending"
    assert _container(sweep_env, young_alive)["status"] == "claimed"
    assert _container(sweep_env, young_ghost)["status"] == "claimed"
    released = _container(sweep_env, old_ghost)
    assert released["status"] == "pending" and released["claimed_by"] is None
    assert released["attempts"] == 2, "attempt history kept for the retry cap"
    assert _occ_paths(sweep_env, old_ghost) == []
    dead = _container(sweep_env, exhausted)
    assert (dead["status"], dead["failure_reason"]) == ("failed", "retries_exhausted")
    assert reap(eng, settings).released == 0, "idempotent"


def test_restarted_worker_releases_its_own_claims_immediately(sweep_env) -> None:
    settings = SweepSettings.from_env()
    mine = _claimed(sweep_env, "pod-a/p3", 1, 5)
    other = _claimed(sweep_env, "pod-a/p4", 1, 5)
    counts = release_own_claims(sweep_env.engine, "pod-a/p3", settings)
    assert counts.released == 1
    assert _container(sweep_env, mine)["status"] == "pending"
    assert _container(sweep_env, other)["status"] == "claimed"


def test_claim_sets_claim_columns(sweep_env) -> None:
    cid = sweep_env.seed_loose({"c/a.stl": b"solid c"})
    claim = claim_one(sweep_env.engine, "claimer/p0")
    assert claim is not None and claim.id == cid and claim.attempt == 1
    row = _container(sweep_env, cid)
    assert row["status"] == "claimed" and row["claimed_by"] == "claimer/p0"
    assert row["claimed_at"] is not None and row["attempts"] == 1
    assert claim_one(sweep_env.engine, "claimer/p1") is None


# ------------------------------------------------------------------ nested rows (scripted engine)


def _scripted_nested(ref, sink, caps, scratch, *, isolate=True) -> Result:
    s = lambda b: sha(b)  # noqa: E731
    sink.member(("a.stl",), s(b"a"), 1, "mesh", 12, 1)
    sink.member(("inner.zip",), s(b"inner"), 5, "archive", None, 1)
    sink.nested_archive(("inner.zip",), s(b"inner"), 5)
    sink.member(("inner.zip", "b.stl"), s(b"b"), 1, "mesh", 4, 2)
    sink.member(("inner.zip", "deep.zip"), s(b"deep"), 4, "archive", None, 2)
    sink.nested_archive(("inner.zip", "deep.zip"), s(b"deep"), 4)
    sink.refused(("inner.zip", "deep.zip", "../evil.stl"), "parent_traversal")
    sink.nested_result(
        ("inner.zip", "deep.zip"),
        Result("failed", "reader_error", 0, 0, 3, format="zip", detail="truncated"),
    )
    sink.nested_result(("inner.zip",), Result("done", None, 2, 5, 3, format="zip"))
    sink.member(("too-deep.zip",), s(b"td"), 2, "archive", None, 1)
    sink.nested_archive(("too-deep.zip",), s(b"td"), 2)
    sink.nested_result(("too-deep.zip",), Result("failed", "spool_exceeded", 0, 0, 2))
    return Result("done", None, 3, 8, 3, format="rar5", reader="libarchive")


def test_nested_archives_become_child_containers(sweep_env, monkeypatch) -> None:
    monkeypatch.setattr(sweep, "_engine_process", _scripted_nested)
    top = sweep_env.seed_archive("pack.rar", b"Rar!\x1a\x07\x01\x00fake", fmt="rar5")
    for _ in range(2):  # second pass: purge + rebuild, never duplicate child rows
        _run(sweep_env)
        with sweep_env.engine.begin() as conn:
            conn.exec_driver_sql(f"UPDATE containers SET status = 'pending' WHERE id = {top}")
    _run(sweep_env)
    kids = sweep_env.rows(
        "SELECT * FROM containers WHERE kind = 'nested' ORDER BY depth, id",
    )
    assert len(kids) == 3
    inner, too_deep, deep = (
        next(k for k in kids if list(k["parent_chain"]) == ["inner.zip"]),
        next(k for k in kids if list(k["parent_chain"]) == ["too-deep.zip"]),
        next(k for k in kids if list(k["parent_chain"]) == ["inner.zip", "deep.zip"]),
    )
    assert inner["parent_container_id"] == top and inner["depth"] == 2
    assert inner["status"] == "done" and inner["members"] == 2
    assert inner["blob_sha"] == sha(b"inner") and inner["format"] == "zip"
    assert deep["parent_container_id"] == inner["id"] and deep["depth"] == 3
    assert (deep["status"], deep["failure_reason"]) == ("failed", "reader_error")
    assert json.loads(deep["notes"])["refused"] == {"parent_traversal": 1}
    assert (too_deep["status"], too_deep["failure_reason"]) == ("failed", "spool_exceeded")
    assert _occ_paths(sweep_env, top) == ["a.stl", "inner.zip", "too-deep.zip"]
    assert _occ_paths(sweep_env, inner["id"]) == ["inner.zip\x1fb.stl", "inner.zip\x1fdeep.zip"]
    top_row = _container(sweep_env, top)
    assert top_row["status"] == "done" and top_row["format"] == "rar5"
    assert top_row["attempts"] == 3


# ---------------------------------------------------------- unsupported_format -> loose re-queue


def _not_an_archive(ref, sink, caps, scratch, *, isolate=True) -> Result:
    if ref.kind == "loose_batch":
        return sweep._engine_process_impl(ref, sink, caps, scratch, isolate=isolate)
    return Result("failed", "unsupported_format", 0, 0, 1, format=None, detail="no signature")


def test_unsupported_format_is_requeued_as_loose_batch(sweep_env, monkeypatch) -> None:
    monkeypatch.setattr(sweep, "_engine_process", _not_an_archive)
    data = b'{"osgjs": "plain json despite the .gz name"}'
    orig = sweep_env.seed_archive("Viewer/model_file.bin.gz", data, fmt=None)
    stats = _run(sweep_env)
    assert stats.outcomes["requeued/unsupported_format"] == 1
    row = _container(sweep_env, orig)
    assert row["status"] == "done" and row["failure_reason"] is None
    notes = json.loads(row["notes"])
    assert notes["engine_reason"] == "unsupported_format"
    new = _container(sweep_env, notes["superseded_by"])
    assert new["kind"] == "loose_batch" and new["requeued_from_id"] == orig
    assert new["status"] == "done" and new["members"] == 1
    occ = sweep_env.rows("SELECT * FROM occurrences WHERE container_id = :c", c=new["id"])
    assert [list(o["member_chain"]) for o in occ] == [["Viewer/model_file.bin.gz"]]
    assert occ[0]["blob_sha"] == sha(data)

    with sweep_env.engine.begin() as conn:  # re-sweeping the original reuses the same batch
        conn.exec_driver_sql(f"UPDATE containers SET status = 'pending' WHERE id = {orig}")
    _run(sweep_env)
    requeued = sweep_env.scalar(
        "SELECT count(*) FROM containers WHERE requeued_from_id = :o", o=orig
    )
    assert requeued == 1
    assert sweep_env.scalar("SELECT count(*) FROM occurrences") == 1


# ------------------------------------------------------------------------------- real engine


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


@needs_native
def test_real_engine_nested_zip_depth3(sweep_env) -> None:
    leaf = b"solid leaf\nendsolid leaf\n"
    inner = _zip({"leaf.stl": leaf})
    mid = _zip({"inner.zip": inner, "mid.txt": b"mid"})
    outer = _zip({"mid.zip": mid, "top.txt": b"top"})
    top = sweep_env.seed_archive("Pack/outer.zip", outer, fmt="zip")
    _run(sweep_env)
    row = _container(sweep_env, top)
    assert row["status"] == "done", row["notes"]
    kids = sweep_env.rows("SELECT * FROM containers WHERE kind = 'nested' ORDER BY depth")
    assert [list(k["parent_chain"]) for k in kids] == [["mid.zip"], ["mid.zip", "inner.zip"]]
    assert [k["status"] for k in kids] == ["done", "done"]
    assert kids[1]["parent_container_id"] == kids[0]["id"]
    chains = {
        tuple(r["member_chain"]): r["blob_sha"]
        for r in sweep_env.rows("SELECT member_chain, blob_sha FROM occurrences")
    }
    assert chains[("mid.zip", "inner.zip", "leaf.stl")] == sha(leaf)
    assert len(chains) == 5


@needs_native
def test_real_engine_fixture_zip_in_rar(sweep_env) -> None:
    import shutil

    shutil.copy(FIXTURES / "zip_in_rar.rar", sweep_env.root / "zip_in_rar.rar")
    top = sweep_env.seed_archive("zip_in_rar.rar", fmt="rar5")
    _run(sweep_env)
    manifest = json.loads((FIXTURES / "manifest.json").read_text())["zip_in_rar.rar"]
    got = {
        tuple(r["member_chain"]): r["blob_sha"]
        for r in sweep_env.rows("SELECT member_chain, blob_sha FROM occurrences")
    }
    assert got == {tuple(m["chain"]): m["sha256"] for m in manifest["members"]}
    assert _container(sweep_env, top)["status"] == "done"
    kid = sweep_env.rows("SELECT * FROM containers WHERE kind = 'nested'")
    assert [list(k["parent_chain"]) for k in kid] == [["inner.zip"]]


@needs_native
def test_real_engine_not_an_archive_requeued(sweep_env) -> None:
    data = b'{"json": true}' * 10
    orig = sweep_env.seed_archive("V/scene.osgjs.gz", data, fmt=None)
    _run(sweep_env)
    row = _container(sweep_env, orig)
    assert row["status"] == "done", row["notes"]
    new_id = json.loads(row["notes"])["superseded_by"]
    assert _container(sweep_env, new_id)["status"] == "done"
    assert sweep_env.scalar("SELECT blob_sha FROM occurrences") == sha(data)


# ------------------------------------------------------------------------- status / metrics


def test_status_and_metrics_report_progress(sweep_env) -> None:
    for i in range(3):
        sweep_env.seed_loose({f"s{i}/a.stl": f"solid {i}".encode()})
    pending = sweep_env.seed_loose({"later/a.stl": b"solid later"})
    _run(sweep_env, max_containers=3)
    snap = collect_status(sweep_env.engine)
    by = {(r["kind"], r["status"]): r["count"] for r in snap["containers"]}
    assert by == {("loose_batch", "done"): 3, ("loose_batch", "pending"): 1}
    assert snap["blobs"] == 3 and snap["occurrences"] == 3
    assert snap["remaining_containers"] == 1
    assert snap["source_bytes_remaining"] == len(b"solid later")
    assert snap["rates"]["5m"]["containers_per_min"] > 0
    assert snap["eta_seconds"] is not None
    text_out = format_status(snap)
    assert "loose_batch" in text_out and "ETA" in text_out
    metrics = metrics_text(snap)
    assert 'forge_containers{kind="loose_batch",status="done"} 3' in metrics
    assert "forge_source_bytes_per_second" in metrics
    assert pending


def test_metrics_http_endpoint(sweep_env) -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = serve_metrics(sweep_env.engine, port)
    try:
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=10).read()
        assert b"forge_up 1" in body
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5).status == 200
    finally:
        server.shutdown()


def test_cli_supervisor_drains_queue(sweep_env) -> None:
    ids = [sweep_env.seed_loose({f"cli{i}/a.stl": f"solid cli {i}".encode()}) for i in range(10)]
    env = {**os.environ, "FORGE_DB_URL": sweep_env.db_url}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "forge.cli",
            "sweep",
            "--worker",
            "--procs",
            "2",
            "--once",
            "--worker-id",
            "cli-pod",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    rows = sweep_env.rows("SELECT id, status, claimed_by FROM containers ORDER BY id")
    assert [r["id"] for r in rows] == ids
    assert all(r["status"] == "done" for r in rows)
    assert {r["claimed_by"].split("/")[0] for r in rows} == {"cli-pod"}
    run = sweep_env.rows("SELECT * FROM sweep_runs WHERE kind = 'sweep'")
    assert run[0]["containers_done"] == 10 and run[0]["finished_at"] is not None
    status = subprocess.run(
        [sys.executable, "-m", "forge.cli", "status", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["blobs"] == 10


@pytest.mark.parametrize("bad", ["FORGE_SCRATCH", "FORGE_SOURCE_ROOT"])
def test_settings_fail_loud_without_paths(sweep_env, monkeypatch, bad) -> None:
    from forge.config import ConfigError

    monkeypatch.delenv(bad)
    with pytest.raises(ConfigError):
        SweepSettings.from_env()
