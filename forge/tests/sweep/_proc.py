"""Entry points for spawned worker processes in the sweep tests (must be importable)."""

from __future__ import annotations

import time

from forge import sweep
from forge.engine import Result
from forge.hashing import hash_file_full


def drain(worker_id: str, db_url: str) -> list[int]:
    """Run one worker until the queue is empty; return the container ids it processed."""
    stats = sweep.worker_loop(worker_id, sweep.SweepSettings.from_env(), db_url=db_url, once=True)
    return stats.processed


def _stall_after_first_member(ref, sink, caps, scratch, *, isolate=True) -> Result:
    """Hash and flush the first file for real, then hang (the test kills us here)."""
    first = ref.paths[0]
    digest, size, tri, _head = hash_file_full(first, head_bytes=16)
    sink.member((str(first),), digest, size, "mesh", tri, 0)
    sink.flush()
    time.sleep(3600)
    raise AssertionError("not reached")


def stall_worker(worker_id: str, db_url: str) -> None:
    """A worker that claims, writes one whole member, and then never finishes."""
    sweep._engine_process = _stall_after_first_member
    sweep.worker_loop(worker_id, sweep.SweepSettings.from_env(), db_url=db_url, once=False)


def stall_child(worker_id: str, db_url: str) -> None:
    """Same, but through the real child entry point (SIGTERM handler installed)."""
    sweep._engine_process = _stall_after_first_member
    sweep._child_main(worker_id, db_url, False, None)
