"""Sweep runner (INIT-032/SPEC-007): claim pending containers, run the engine, write the catalog.

``forge sweep --worker`` starts a supervisor that spawns ``--procs`` worker processes (each with
its own DB connection pool). A worker loop:

1. claims one ``pending`` container (``FOR UPDATE SKIP LOCKED``): ``claimed``, ``claimed_by``,
   ``claimed_at``, ``attempts + 1``;
2. deletes anything a previous attempt wrote for it (occurrences, nested child rows) so a retry
   never duplicates;
3. runs ``forge.engine.process(..., isolate=True)`` with a :class:`DbSink` that batch-inserts
   blobs (``ON CONFLICT DO NOTHING``) and occurrences. Members arrive only after they are fully
   hashed (GR-004), so every flushed row is a whole member;
4. marks the container ``done`` / ``failed`` (``failure_reason``, ``members``, ``bytes_read``,
   ``finished_at``, ``notes``).

Every write after the claim re-checks ownership (``status = 'claimed'``, ``claimed_by``,
``attempts``), so a worker whose claim was reaped can never write into someone else's attempt.

Reaper (each worker, periodically; idempotent): a claim older than the wall cap + grace, or held
by a worker whose heartbeat stopped, returns to ``pending``; past ``max_attempts`` it becomes
``failed/retries_exhausted``. A restarted worker process releases its own old claims at start,
so a pod that is OOM-killed and restarted recovers its containers immediately.

Not-an-archive (``failed/unsupported_format`` with ``format=None``) is re-queued as a
``loose_batch`` of the same source files (``requeued_from_id``) and the original is marked
``done`` with ``notes.superseded_by`` — the bytes still get a blob (REQ-001).
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import random
import signal
import socket
import sys
import threading
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from forge.config import ConfigError, ForgeConfig, require_db_url
from forge.db.models import Blob, Occurrence, join_member_path
from forge.db.session import get_session_factory, pending_claim_stmt
from forge.engine import Caps, ContainerRef, Result
from forge.engine import process as _engine_process_impl

# Indirection so tests can substitute a scripted engine inside a worker process.
_engine_process: Callable[..., Result] = _engine_process_impl

STALE_GRACE_SECONDS = 600


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


def log(event: str, **fields) -> None:
    rec = {"ts": round(time.time(), 3), "event": event, **fields}
    print(json.dumps(rec, default=str, separators=(",", ":")), flush=True)


@dataclass(frozen=True)
class SweepSettings:
    source_root: Path
    scratch: Path
    caps: Caps
    stale_seconds: float  # a claim older than this is dead regardless of heartbeats
    heartbeat_seconds: float
    heartbeat_stale_seconds: float  # a claim whose worker has not beaten for this long is dead
    poll_seconds: float  # idle sleep when nothing is pending
    reap_every_seconds: float
    flush_members: int = 500
    max_attempts: int = 2  # attempts > max_attempts -> failed/retries_exhausted

    @classmethod
    def from_env(cls) -> SweepSettings:
        cfg = ForgeConfig.from_env()
        root = cfg.require_source_root()
        if not cfg.scratch:
            raise ConfigError("FORGE_SCRATCH is not configured (local scratch dir for spools).")
        caps = Caps.from_env()
        return cls(
            source_root=Path(root),
            scratch=Path(cfg.scratch),
            caps=caps,
            stale_seconds=_env_float(
                "FORGE_SWEEP_STALE_SECONDS",
                caps.wall_seconds + caps.kill_grace_seconds + STALE_GRACE_SECONDS,
            ),
            heartbeat_seconds=_env_float("FORGE_SWEEP_HEARTBEAT_SECONDS", 30),
            heartbeat_stale_seconds=_env_float("FORGE_SWEEP_HEARTBEAT_STALE_SECONDS", 300),
            poll_seconds=_env_float("FORGE_SWEEP_POLL_SECONDS", 30),
            reap_every_seconds=_env_float("FORGE_SWEEP_REAP_SECONDS", 60),
            flush_members=int(_env_float("FORGE_SWEEP_FLUSH_MEMBERS", 500)),
            max_attempts=int(_env_float("FORGE_SWEEP_MAX_ATTEMPTS", 2)),
        )


class LostClaim(RuntimeError):
    """The container is no longer claimed by this worker attempt (reaped or reset)."""


class Shutdown(BaseException):
    """Raised in a worker on SIGTERM while a container is in flight; the claim is released."""


@dataclass
class _ProcState:
    busy: bool = False  # inside the engine: SIGTERM aborts the container
    stop: threading.Event = field(default_factory=threading.Event)
    # Claims this process could not hand back because the DB was down; retried between
    # containers so a Postgres restart does not strand them until the stale window.
    unreleased: list = field(default_factory=list)


_STATE = _ProcState()


def _on_sigterm(signum, frame) -> None:
    _STATE.stop.set()
    if _STATE.busy:
        _STATE.busy = False
        raise Shutdown()


# --------------------------------------------------------------------------------------- claim


@dataclass(frozen=True)
class Claim:
    id: int
    kind: str  # archive | loose_batch
    attempt: int
    worker_id: str
    source_file_id: int | None
    files: tuple[tuple[str, int], ...]  # (source_files.path relative to the root, size), ordinal
    source_bytes: int


_CLAIM_FILES = text(
    """
    SELECT sf.path, sf.size FROM container_files cf
    JOIN source_files sf ON sf.id = cf.source_file_id
    WHERE cf.container_id = :cid
    ORDER BY cf.ordinal
    """
)

_OWNED = (
    "SELECT 1 FROM containers WHERE id = :cid AND status = 'claimed' "
    "AND claimed_by = :w AND attempts = :a"
)
_OWNED_SHARE = text(_OWNED + " FOR SHARE")
_OWNED_UPDATE = text(_OWNED + " FOR UPDATE")


def claim_one(engine: Engine, worker_id: str) -> Claim | None:
    """Claim the lowest-id pending container, or return None when nothing is pending."""
    factory = get_session_factory(engine)
    with factory() as session, session.begin():
        row = session.execute(pending_claim_stmt(1)).scalar_one_or_none()
        if row is None:
            return None
        files = tuple(
            (str(path), int(size))
            for path, size in session.execute(_CLAIM_FILES, {"cid": row.id}).all()
        )
        attempt = int(row.attempts) + 1
        session.execute(
            text(
                """
                UPDATE containers SET status = 'claimed', claimed_by = :w, claimed_at = now(),
                    attempts = :a, source_bytes = :sb, finished_at = NULL
                WHERE id = :cid
                """
            ),
            {"w": worker_id, "a": attempt, "sb": sum(s for _, s in files), "cid": row.id},
        )
        return Claim(
            id=int(row.id),
            kind=str(row.kind.value if hasattr(row.kind, "value") else row.kind),
            attempt=attempt,
            worker_id=worker_id,
            source_file_id=row.source_file_id,
            files=files,
            source_bytes=sum(s for _, s in files),
        )


def _assert_owned(conn: Connection, claim: Claim, *, for_update: bool = False) -> None:
    stmt = _OWNED_UPDATE if for_update else _OWNED_SHARE
    if conn.execute(stmt, {"cid": claim.id, "w": claim.worker_id, "a": claim.attempt}).first():
        return
    raise LostClaim(f"container {claim.id} attempt {claim.attempt} no longer owned")


# ---------------------------------------------------------------------------- outputs / purge

_DESCENDANTS = text(
    """
    WITH RECURSIVE d AS (
        SELECT id, depth FROM containers WHERE parent_container_id = :cid AND kind = 'nested'
        UNION ALL
        SELECT c.id, c.depth FROM containers c JOIN d ON c.parent_container_id = d.id
        WHERE c.kind = 'nested'
    )
    SELECT id, depth FROM d
    """
)


def nested_descendants(conn: Connection, container_id: int) -> list[tuple[int, int]]:
    return [(int(i), int(d)) for i, d in conn.execute(_DESCENDANTS, {"cid": container_id}).all()]


def purge_outputs(conn: Connection, container_id: int) -> None:
    """Delete everything a previous attempt wrote: occurrences and nested child containers."""
    desc = nested_descendants(conn, container_id)
    ids = [container_id] + [i for i, _ in desc]
    conn.execute(
        text("DELETE FROM occurrences WHERE container_id = ANY(CAST(:ids AS bigint[]))"),
        {"ids": ids},
    )
    for depth in sorted({d for _, d in desc}, reverse=True):  # children before parents
        conn.execute(
            text("DELETE FROM containers WHERE id = ANY(CAST(:ids AS bigint[]))"),
            {"ids": [i for i, d in desc if d == depth]},
        )


def _ext(name: str) -> str | None:
    base = name.split("//", 1)[0].rsplit("/", 1)[-1]
    ext = os.path.splitext(base)[1][1:].lower()
    return ext if ext and len(ext) <= 16 else None


def _notes(
    result: Result | None,
    refused: Counter | None = None,
    examples: list | None = None,
    **extra,
) -> str | None:
    d: dict = {}
    if result is not None:
        if result.reader:
            d["reader"] = result.reader
        if result.detail:
            d["detail"] = result.detail[:500]
        if result.peak_rss_kb:
            d["peak_rss_kb"] = result.peak_rss_kb
        if result.max_depth:
            d["max_depth"] = result.max_depth
    if refused:
        d["refused"] = dict(refused)
        d["refused_examples"] = (examples or [])[:20]
    d.update({k: v for k, v in extra.items() if v is not None})
    return json.dumps(d, separators=(",", ":"), ensure_ascii=True) if d else None


# ----------------------------------------------------------------------------------------- sink


class DbSink:
    """Engine Sink writing blobs, occurrences and nested child containers for one claim.

    Occurrences belong to the container that directly holds the member (ADR D-1): a member of a
    nested archive is attached to that nested child container; ``member_chain`` is the full chain
    from the source container, so ``member_path`` stays unique per container.
    """

    def __init__(self, engine: Engine, claim: Claim, settings: SweepSettings) -> None:
        self.engine = engine
        self.claim = claim
        self.flush_members = max(1, settings.flush_members)
        self.top_depth = 0 if claim.kind == "loose_batch" else 1
        self._rel = (
            {str(settings.source_root / rel): rel for rel, _ in claim.files}
            if claim.kind == "loose_batch"
            else {}
        )
        self._blobs: dict[str, dict] = {}
        self._occ: list[dict] = []
        self.nested: dict[tuple[str, ...], int] = {}
        self._archive_sha: dict[tuple[str, ...], tuple[str, int]] = {}
        self.refused_by: dict[int, Counter] = defaultdict(Counter)
        self.refused_examples: dict[int, list] = defaultdict(list)
        self.members = 0  # occurrences written for the whole tree

    # chain helpers ---------------------------------------------------------------------------
    def _chain(self, chain: tuple[str, ...]) -> tuple[str, ...]:
        if self._rel and chain:
            first = self._rel.get(chain[0], chain[0])
            return (first, *chain[1:])
        return tuple(chain)

    def owner(self, chain: tuple[str, ...]) -> int:
        parent = chain[:-1]
        if not parent:
            return self.claim.id
        return self.nested.get(parent, self.claim.id)

    # Sink protocol ---------------------------------------------------------------------------
    def member(self, chain, sha256, size, kind, triangles, depth) -> None:
        chain = self._chain(chain)
        self._blobs.setdefault(
            sha256,
            {
                "sha256": sha256,
                "size": int(size),
                "kind": kind,
                "ext": _ext(chain[-1]),
                "stl_triangles": triangles,
            },
        )
        self._occ.append(
            {
                "blob_sha": sha256,
                "container_id": self.owner(chain),
                "member_chain": list(chain),
                "member_path": join_member_path(chain),
                "depth": int(depth),
            }
        )
        if kind == "archive":
            self._archive_sha[chain] = (sha256, int(size))
        self.members += 1
        if len(self._occ) >= self.flush_members:
            self.flush()

    def refused(self, chain, reason) -> None:
        chain = self._chain(chain)
        cid = self.owner(chain)
        self.refused_by[cid][reason] += 1
        if len(self.refused_examples[cid]) < 20:
            self.refused_examples[cid].append([list(chain), reason])

    def nested_archive(self, chain, sha256, size) -> None:
        chain = self._chain(chain)
        parent = self.owner(chain)
        claim = self.claim

        def insert(conn: Connection) -> int:
            return int(
                conn.execute(
                    text(
                        """
                        INSERT INTO containers (
                            source_file_id, blob_sha, parent_container_id, parent_chain, kind,
                            depth, status, claimed_by, claimed_at, attempts, source_bytes
                        ) VALUES (
                            :sid, :sha, :pid, CAST(:chain AS text[]), 'nested',
                            :depth, 'claimed', :w, now(), :a, :size
                        ) RETURNING id
                        """
                    ),
                    {
                        "sid": claim.source_file_id,
                        "sha": sha256,
                        "pid": parent,
                        "chain": list(chain),
                        "depth": self.top_depth + len(chain),
                        "w": claim.worker_id,
                        "a": claim.attempt,
                        "size": int(size),
                    },
                ).scalar_one()
            )

        self.nested[chain] = self.flush(extra=insert)

    def nested_result(self, chain, result: Result) -> None:
        chain = self._chain(chain)
        cid = self.nested.get(chain)
        claim = self.claim
        params = {
            "st": result.status,
            "r": result.reason,
            "m": result.members,
            "b": result.bytes_read,
            "fmt": result.format,
            "notes": _notes(
                result,
                self.refused_by.get(cid) if cid else None,
                self.refused_examples.get(cid) if cid else None,
            ),
        }

        def update(conn: Connection) -> int:
            if cid is not None:
                conn.execute(
                    text(
                        """
                        UPDATE containers SET status = CAST(:st AS container_status),
                            failure_reason = CAST(:r AS failure_reason), members = :m,
                            bytes_read = :b, format = :fmt, finished_at = now(), notes = :notes
                        WHERE id = :cid
                        """
                    ),
                    {**params, "cid": cid},
                )
                return cid
            sha, size = self._archive_sha.get(chain, (None, None))
            return int(
                conn.execute(
                    text(
                        """
                        INSERT INTO containers (
                            source_file_id, blob_sha, parent_container_id, parent_chain, kind,
                            depth, status, failure_reason, members, bytes_read, format,
                            claimed_by, claimed_at, attempts, source_bytes, finished_at, notes
                        ) VALUES (
                            :sid, :sha, :pid, CAST(:chain AS text[]), 'nested', :depth,
                            CAST(:st AS container_status), CAST(:r AS failure_reason), :m, :b,
                            :fmt, :w, now(), :a, :size, now(), :notes
                        ) RETURNING id
                        """
                    ),
                    {
                        **params,
                        "sid": claim.source_file_id,
                        "sha": sha,
                        "pid": self.owner(chain),
                        "chain": list(chain),
                        "depth": self.top_depth + len(chain),
                        "w": claim.worker_id,
                        "a": claim.attempt,
                        "size": size,
                    },
                ).scalar_one()
            )

        self.nested[chain] = self.flush(extra=update)

    # writes ----------------------------------------------------------------------------------
    def discard_buffers(self) -> None:
        self._blobs.clear()
        self._occ.clear()

    def flush(self, extra: Callable[[Connection], int] | None = None) -> int | None:
        if not self._blobs and not self._occ and extra is None:
            return None
        out = None
        with self.engine.begin() as conn:
            _assert_owned(conn, self.claim)
            if self._blobs:
                # Sorted keys: concurrent workers lock shared blob keys in the same order.
                rows = [self._blobs[k] for k in sorted(self._blobs)]
                conn.execute(
                    pg_insert(Blob.__table__).on_conflict_do_nothing(index_elements=["sha256"]),
                    rows,
                )
            if self._occ:
                conn.execute(
                    pg_insert(Occurrence.__table__).on_conflict_do_nothing(
                        constraint="uq_occurrences_container_member_path"
                    ),
                    self._occ,
                )
            if extra is not None:
                out = extra(conn)
        self._blobs.clear()
        self._occ.clear()
        return out


# ------------------------------------------------------------------------------ finish / release


def _requeue_as_loose(conn: Connection, claim: Claim) -> int:
    """Re-queue the source files of a not-actually-an-archive container as a loose_batch."""
    existing = conn.execute(
        text(
            """
            SELECT id FROM containers
            WHERE requeued_from_id = :cid AND kind = 'loose_batch'
            ORDER BY id LIMIT 1
            """
        ),
        {"cid": claim.id},
    ).scalar()
    if existing is not None:
        new_id = int(existing)
        purge_outputs(conn, new_id)
        conn.execute(
            text(
                """
                UPDATE containers SET status = 'pending', failure_reason = NULL,
                    claimed_by = NULL, claimed_at = NULL, attempts = 0, members = 0,
                    bytes_read = 0, finished_at = NULL
                WHERE id = :id
                """
            ),
            {"id": new_id},
        )
        conn.execute(text("DELETE FROM container_files WHERE container_id = :id"), {"id": new_id})
    else:
        new_id = int(
            conn.execute(
                text(
                    """
                    INSERT INTO containers (
                        source_file_id, kind, depth, status, requeued_from_id, notes
                    ) VALUES (:sid, 'loose_batch', 0, 'pending', :cid, :notes)
                    RETURNING id
                    """
                ),
                {
                    "sid": claim.source_file_id,
                    "cid": claim.id,
                    "notes": _notes(None, requeued_from=claim.id, reason="unsupported_format"),
                },
            ).scalar_one()
        )
    conn.execute(
        text(
            """
            INSERT INTO container_files (container_id, source_file_id, ordinal)
            SELECT :new, source_file_id, ordinal FROM container_files WHERE container_id = :cid
            """
        ),
        {"new": new_id, "cid": claim.id},
    )
    return new_id


def should_requeue(claim: Claim, result: Result) -> bool:
    return (
        claim.kind == "archive"
        and result.status == "failed"
        and result.reason == "unsupported_format"
        and result.format is None
    )


def finish(
    engine: Engine, claim: Claim, result: Result, sink: DbSink, run_id: int | None
) -> tuple[str, str | None]:
    """Flush the sink and record the outcome. Returns (status, reason); raises LostClaim."""
    sink.flush()
    status, reason = result.status, result.reason
    with engine.begin() as conn:
        _assert_owned(conn, claim, for_update=True)
        extra: dict = {}
        if should_requeue(claim, result):
            new_id = _requeue_as_loose(conn, claim)
            status, reason = "done", None
            extra = {"superseded_by": new_id, "engine_reason": "unsupported_format"}
        conn.execute(
            text(
                """
                UPDATE containers SET status = CAST(:st AS container_status),
                    failure_reason = CAST(:r AS failure_reason), members = :m, bytes_read = :b,
                    format = COALESCE(:fmt, format), finished_at = now(), notes = :notes
                WHERE id = :cid
                """
            ),
            {
                "st": status,
                "r": reason,
                "m": result.members,
                "b": result.bytes_read,
                "fmt": result.format,
                "notes": _notes(
                    result,
                    sink.refused_by.get(claim.id),
                    sink.refused_examples.get(claim.id),
                    **extra,
                ),
                "cid": claim.id,
            },
        )
        if sink.nested:
            # A child the engine never closed (should not happen) must not stay 'claimed'.
            conn.execute(
                text(
                    """
                    UPDATE containers SET status = 'failed',
                        failure_reason = CAST(:r AS failure_reason), finished_at = now()
                    WHERE id = ANY(CAST(:ids AS bigint[])) AND status = 'claimed'
                    """
                ),
                {"r": reason or "reader_error", "ids": list(sink.nested.values())},
            )
        done, failed = (1, 0) if status == "done" else (0, 1)
        conn.execute(
            text(
                """
                UPDATE sweep_workers SET containers_done = containers_done + :d,
                    containers_failed = containers_failed + :f, bytes_read = bytes_read + :b,
                    source_bytes = source_bytes + :s, current_container_id = NULL,
                    last_seen = now()
                WHERE worker_id = :w
                """
            ),
            {
                "d": done,
                "f": failed,
                "b": result.bytes_read,
                "s": claim.source_bytes,
                "w": claim.worker_id,
            },
        )
        if run_id is not None:
            conn.execute(
                text(
                    """
                    UPDATE sweep_runs SET containers_claimed = containers_claimed + 1,
                        containers_done = containers_done + :d,
                        containers_failed = containers_failed + :f,
                        occurrences_created = occurrences_created + :o,
                        bytes_read = bytes_read + :s
                    WHERE id = :run
                    """
                ),
                {"d": done, "f": failed, "o": sink.members, "s": claim.source_bytes, "run": run_id},
            )
    return status, reason


def release_claim(engine: Engine, claim: Claim, *, count_attempt: bool) -> bool:
    """Return an in-flight claim to pending (shutdown / DB trouble). False if no longer owned."""
    with engine.begin() as conn:
        try:
            _assert_owned(conn, claim, for_update=True)
        except LostClaim:
            return False
        purge_outputs(conn, claim.id)
        conn.execute(
            text(
                """
                UPDATE containers SET status = 'pending', claimed_by = NULL, claimed_at = NULL,
                    attempts = GREATEST(attempts - :dec, 0)
                WHERE id = :cid
                """
            ),
            {"cid": claim.id, "dec": 0 if count_attempt else 1},
        )
    return True


# --------------------------------------------------------------------------------------- reaper

_REAP_STALE = text(
    """
    SELECT c.id, c.attempts, c.claimed_by FROM containers c
    LEFT JOIN sweep_workers w ON w.worker_id = c.claimed_by
    WHERE c.status = 'claimed' AND c.kind <> 'nested'
      AND (
        c.claimed_at < now() - make_interval(secs => :stale)
        OR (w.worker_id IS NULL AND c.claimed_at < now() - make_interval(secs => :hb))
        OR w.last_seen < now() - make_interval(secs => :hb)
      )
    ORDER BY c.id
    LIMIT 500
    FOR UPDATE OF c SKIP LOCKED
    """
)

_REAP_OWN = text(
    """
    SELECT id, attempts, claimed_by FROM containers
    WHERE status = 'claimed' AND kind <> 'nested' AND claimed_by = :w
    ORDER BY id
    FOR UPDATE SKIP LOCKED
    """
)


@dataclass
class ReapCounts:
    released: int = 0
    exhausted: int = 0


def _reap_rows(conn: Connection, rows, max_attempts: int, why: str) -> ReapCounts:
    counts = ReapCounts()
    for cid, attempts, claimed_by in rows:
        cid = int(cid)
        if int(attempts) > max_attempts:
            conn.execute(
                text(
                    """
                    UPDATE containers SET status = 'failed', failure_reason = 'retries_exhausted',
                        finished_at = now(), notes = :notes
                    WHERE id = :cid
                    """
                ),
                {
                    "cid": cid,
                    "notes": _notes(
                        None,
                        detail=f"{attempts} attempts; last worker {claimed_by} lost ({why})",
                    ),
                },
            )
            desc = [i for i, _ in nested_descendants(conn, cid)]
            if desc:
                conn.execute(
                    text(
                        """
                        UPDATE containers SET status = 'failed',
                            failure_reason = 'retries_exhausted', finished_at = now()
                        WHERE id = ANY(CAST(:ids AS bigint[])) AND status = 'claimed'
                        """
                    ),
                    {"ids": desc},
                )
            counts.exhausted += 1
            log("reap", container=cid, to="failed/retries_exhausted", attempts=attempts, why=why)
        else:
            purge_outputs(conn, cid)
            conn.execute(
                text(
                    """
                    UPDATE containers SET status = 'pending', claimed_by = NULL, claimed_at = NULL
                    WHERE id = :cid
                    """
                ),
                {"cid": cid},
            )
            counts.released += 1
            log("reap", container=cid, to="pending", attempts=attempts, why=why)
    return counts


def reap(engine: Engine, settings: SweepSettings) -> ReapCounts:
    """Return stale claims to pending (or retries_exhausted). Safe to run from every worker."""
    with engine.begin() as conn:
        rows = conn.execute(
            _REAP_STALE,
            {"stale": settings.stale_seconds, "hb": settings.heartbeat_stale_seconds},
        ).all()
        return _reap_rows(conn, rows, settings.max_attempts, "stale")


def release_own_claims(engine: Engine, worker_id: str, settings: SweepSettings) -> ReapCounts:
    """A (re)started worker process owns nothing yet: any claim under its id is orphaned."""
    with engine.begin() as conn:
        rows = conn.execute(_REAP_OWN, {"w": worker_id}).all()
        return _reap_rows(conn, rows, settings.max_attempts, "worker_restart")


# ------------------------------------------------------------------------------------ heartbeat


def register_worker(engine: Engine, worker_id: str, run_id: int | None) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO sweep_workers (worker_id, sweep_run_id, host, pid)
                VALUES (:w, :run, :host, :pid)
                ON CONFLICT (worker_id) DO UPDATE SET sweep_run_id = EXCLUDED.sweep_run_id,
                    host = EXCLUDED.host, pid = EXCLUDED.pid, started_at = now(),
                    last_seen = now(), current_container_id = NULL
                """
            ),
            {"w": worker_id, "run": run_id, "host": socket.gethostname(), "pid": os.getpid()},
        )


class Heartbeat(threading.Thread):
    def __init__(self, engine: Engine, worker_id: str, interval: float) -> None:
        super().__init__(name=f"heartbeat-{worker_id}", daemon=True)
        self.engine = engine
        self.worker_id = worker_id
        self.interval = interval
        self.current: int | None = None
        self._halt = threading.Event()

    def beat(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE sweep_workers SET last_seen = now(), current_container_id = :c
                    WHERE worker_id = :w
                    """
                ),
                {"c": self.current, "w": self.worker_id},
            )

    def run(self) -> None:
        while not self._halt.wait(self.interval):
            try:
                self.beat()
            except SQLAlchemyError as exc:
                log("heartbeat_error", worker=self.worker_id, error=type(exc).__name__)

    def halt(self) -> None:
        self._halt.set()


# ---------------------------------------------------------------------------------- worker loop


@dataclass
class WorkerStats:
    processed: list[int] = field(default_factory=list)
    outcomes: Counter = field(default_factory=Counter)


def _work_remaining(engine: Engine) -> bool:
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM containers
                        WHERE status IN ('pending', 'claimed') AND kind <> 'nested'
                    )
                    """
                )
            ).scalar()
        )


def _depth_for(claim: Claim) -> int:
    return 0 if claim.kind == "loose_batch" else 1


def run_claim(
    engine: Engine, claim: Claim, settings: SweepSettings, run_id: int | None
) -> tuple[str, str | None]:
    """Process one claimed container end to end. Returns (outcome, reason)."""
    started = time.monotonic()
    display = claim.files[0][0] if claim.files else f"container {claim.id}"
    log(
        "claim",
        container=claim.id,
        kind=claim.kind,
        attempt=claim.attempt,
        worker=claim.worker_id,
        files=len(claim.files),
        source_bytes=claim.source_bytes,
        path=display,
    )
    sink = DbSink(engine, claim, settings)
    try:
        with engine.begin() as conn:
            _assert_owned(conn, claim, for_update=True)
            purge_outputs(conn, claim.id)
        if not claim.files:
            result = Result(
                "failed",
                "reader_error",
                0,
                0,
                _depth_for(claim),
                detail="container has no source files",
            )
        else:
            ref = ContainerRef(
                kind=claim.kind,
                paths=tuple(settings.source_root / rel for rel, _ in claim.files),
                display=display,
            )
            _STATE.busy = True
            try:
                result = _engine_process(ref, sink, settings.caps, settings.scratch, isolate=True)
            finally:
                _STATE.busy = False
        status, reason = finish(engine, claim, result, sink, run_id)
    except LostClaim as exc:
        log("lost_claim", container=claim.id, worker=claim.worker_id, detail=str(exc))
        return "lost", None
    except Shutdown:
        _STATE.busy = False
        ok = release_claim(engine, claim, count_attempt=False)
        log("released", container=claim.id, worker=claim.worker_id, reason="shutdown", ok=ok)
        raise
    except SQLAlchemyError as exc:
        log("db_error", container=claim.id, worker=claim.worker_id, error=repr(exc)[:300])
        _release_or_defer(engine, claim)
        _STATE.stop.wait(min(5.0, settings.poll_seconds * 10))
        return "db_error", None
    except ValueError:
        # Misconfigured scratch / source (engine guard): fatal for this worker.
        release_claim(engine, claim, count_attempt=False)
        raise
    except Exception as exc:  # noqa: BLE001 - a sweep bug must not lose the container silently
        log("sweep_exception", container=claim.id, error=repr(exc)[:300])
        result = Result(
            "failed",
            "reader_error",
            0,
            0,
            _depth_for(claim),
            detail=f"sweep: {type(exc).__name__}: {exc}"[:300],
        )
        sink.discard_buffers()  # members already flushed were whole (GR-004); keep them
        try:
            status, reason = finish(engine, claim, result, sink, run_id)
        except LostClaim:
            return "error", None
        except SQLAlchemyError:
            _release_or_defer(engine, claim)
            return "error", None
    log(
        "finish",
        container=claim.id,
        kind=claim.kind,
        status=status,
        reason=reason,
        engine_reason=result.reason,
        members=result.members,
        tree_members=sink.members,
        bytes_read=result.bytes_read,
        source_bytes=claim.source_bytes,
        reader=result.reader,
        format=result.format,
        peak_rss_kb=result.peak_rss_kb,
        seconds=round(time.monotonic() - started, 2),
    )
    if status == "done" and should_requeue(claim, result):
        return "requeued", "unsupported_format"
    return status, reason


def _release_or_defer(engine: Engine, claim: Claim) -> None:
    try:
        release_claim(engine, claim, count_attempt=False)
    except SQLAlchemyError:
        _STATE.unreleased.append(claim)


def retry_deferred_releases(engine: Engine) -> None:
    """Hand back claims a DB outage stranded (between containers: nothing is in flight)."""
    while _STATE.unreleased:
        claim = _STATE.unreleased[0]
        ok = release_claim(engine, claim, count_attempt=False)
        _STATE.unreleased.pop(0)
        log("released", container=claim.id, worker=claim.worker_id, reason="db_outage", ok=ok)


def worker_loop(
    worker_id: str,
    settings: SweepSettings,
    *,
    db_url: str,
    once: bool = False,
    run_id: int | None = None,
    max_containers: int | None = None,
) -> WorkerStats:
    """Claim and process containers until stopped (or, with ``once``, until the queue drains)."""
    engine = create_engine(db_url, pool_pre_ping=True, pool_size=2, max_overflow=2)
    stats = WorkerStats()
    hb = Heartbeat(engine, worker_id, settings.heartbeat_seconds)
    try:
        released = release_own_claims(engine, worker_id, settings)
        if released.released or released.exhausted:
            log("released_own", worker=worker_id, **released.__dict__)
        register_worker(engine, worker_id, run_id)
        hb.start()
        log("worker_start", worker=worker_id, pid=os.getpid(), once=once)
        next_reap = 0.0
        backoff = 1.0
        while not _STATE.stop.is_set():
            if max_containers is not None and len(stats.processed) >= max_containers:
                break
            now = time.monotonic()
            try:
                retry_deferred_releases(engine)
                if now >= next_reap:
                    reap(engine, settings)
                    next_reap = now + settings.reap_every_seconds * random.uniform(0.8, 1.2)
                claim = claim_one(engine, worker_id)
                if claim is None and once and not _work_remaining(engine):
                    break
            except SQLAlchemyError as exc:
                log("db_error", worker=worker_id, error=repr(exc)[:300])
                _STATE.stop.wait(backoff)
                backoff = min(backoff * 2, 60)
                continue
            backoff = 1.0
            if claim is None:
                _STATE.stop.wait(settings.poll_seconds)
                continue
            hb.current = claim.id
            outcome, reason = run_claim(engine, claim, settings, run_id)
            hb.current = None
            stats.processed.append(claim.id)
            stats.outcomes[outcome if reason is None else f"{outcome}/{reason}"] += 1
    finally:
        hb.halt()
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE sweep_workers SET current_container_id = NULL, "
                        "last_seen = now() WHERE worker_id = :w"
                    ),
                    {"w": worker_id},
                )
        except SQLAlchemyError:
            pass
        engine.dispose()
        log("worker_stop", worker=worker_id, processed=len(stats.processed))
    return stats


def _child_main(worker_id: str, db_url: str, once: bool, run_id: int | None) -> None:
    signal.signal(signal.SIGTERM, _on_sigterm)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    settings = SweepSettings.from_env()
    try:
        worker_loop(worker_id, settings, db_url=db_url, once=once, run_id=run_id)
    except Shutdown:
        pass


# ----------------------------------------------------------------------------------- supervisor


def _start_run(engine: Engine, worker_base: str) -> int:
    with engine.begin() as conn:
        return int(
            conn.execute(
                text("INSERT INTO sweep_runs (kind, worker_id) VALUES ('sweep', :w) RETURNING id"),
                {"w": worker_base},
            ).scalar_one()
        )


def _finish_run(engine: Engine, run_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE sweep_runs SET finished_at = now() WHERE id = :id"), {"id": run_id}
        )


def run_supervisor(
    *,
    procs: int,
    once: bool,
    metrics_port: int | None,
    worker_base: str | None = None,
) -> int:
    """Spawn ``procs`` worker processes, restart crashed ones, forward SIGTERM, serve /metrics."""
    settings = SweepSettings.from_env()  # fail loud before spawning anything
    db_url = require_db_url()
    base = worker_base or ForgeConfig.from_env().worker_id or socket.gethostname()
    engine = create_engine(db_url, pool_pre_ping=True, pool_size=2, max_overflow=2)
    run_id = _start_run(engine, base)
    log(
        "sweep_start",
        run=run_id,
        worker=base,
        procs=procs,
        once=once,
        stale_seconds=settings.stale_seconds,
        caps=settings.caps.__dict__,
    )
    server = None
    if metrics_port:
        from forge.status import serve_metrics

        server = serve_metrics(engine, metrics_port)

    ctx = mp.get_context("spawn")
    stopping = threading.Event()
    children: dict[int, mp.process.BaseProcess] = {}
    restart_at: dict[int, float] = {}
    failures = 0

    def spawn(i: int) -> None:
        p = ctx.Process(
            target=_child_main,
            args=(f"{base}/p{i}", db_url, once, run_id),
            name=f"forge-sweep-p{i}",
        )
        p.start()
        children[i] = p

    def on_signal(signum, frame) -> None:
        stopping.set()
        for p in list(children.values()):
            if p.is_alive():
                p.terminate()

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    for i in range(procs):
        spawn(i)
    while children or (restart_at and not stopping.is_set()):
        for i, p in list(children.items()):
            if p.is_alive():
                continue
            p.join()
            del children[i]
            code = p.exitcode
            if stopping.is_set() or (once and code == 0):
                continue
            failures += 1
            log("worker_exit", worker=f"{base}/p{i}", code=code, restarting_in=10)
            restart_at[i] = time.monotonic() + 10
        if not stopping.is_set():
            for i, at in list(restart_at.items()):
                if time.monotonic() >= at:
                    del restart_at[i]
                    spawn(i)
        else:
            restart_at.clear()
        stopping.wait(1.0)
    if server is not None:
        server.shutdown()
    try:
        _finish_run(engine, run_id)
    except SQLAlchemyError:
        pass
    engine.dispose()
    log("sweep_stop", run=run_id, worker_restarts=failures)
    return 0


def main_sweep(*, procs: int, once: bool, metrics_port: int | None, worker_id: str | None) -> int:
    try:
        return run_supervisor(
            procs=procs, once=once, metrics_port=metrics_port, worker_base=worker_id
        )
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
