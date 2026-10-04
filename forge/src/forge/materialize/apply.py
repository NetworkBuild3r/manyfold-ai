"""``forge materialize apply`` — execute the active plan. Resume-safe, idempotent, parallel.

Work is claimed from ``materialize_units`` / ``materialize_packs`` with ``FOR UPDATE SKIP LOCKED``
so several processes (and several Job pods) can run at once:

1. **loose units** — hardlink each loose source file into the blob store (no bytes copied);
2. **archive units** — one sequential pass per source container extracting exactly the needed
   members (:class:`forge.materialize.extract.Extractor`), sha256-verified before publish;
3. **packs** — once every blob a pack needs is terminal, hardlink its files from the store into
   ``<v2>/<Category>/<Pack>/`` and write ``datapackage.json``.

A killed worker's claim goes stale (no heartbeat) and is reaped back to ``pending``; its leftover
temp files are removed by the next attempt. Existing correct files are skipped, so a rerun of a
finished plan does nothing.
"""

from __future__ import annotations

import json
import multiprocessing
import os
import signal
import socket
import stat
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from forge import __version__
from forge.config import ConfigError, optional_env
from forge.engine.caps import Caps
from forge.engine.fallback import find_7zz

from .extract import Extractor, TokenBucket, Want
from .guard import GuardError, WriteGuard, is_v2_relative_safe, join_v2, open_guard
from .keywords import pack_keywords
from .paths import DATAPACKAGE
from .store import BlobStore, CopyDisabled, StoreCorrupt, TempWriter, hash_path

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def log(event: str, **fields) -> None:
    rec = {"ts": round(time.time(), 3), "event": event, **fields}
    print(json.dumps(rec, default=str, separators=(",", ":")), flush=True)


def _env_float(name: str, default: float) -> float:
    raw = optional_env(name)
    return float(raw) if raw else default


@dataclass(frozen=True)
class ApplySettings:
    v2_root: Path
    source_root: Path
    scratch: Path
    shared_mount_ack: bool
    caps: Caps
    procs: int = 1
    io_mbps: float = 0.0  # per pod, split across procs; 0 = unlimited
    stale_seconds: float = 900.0
    heartbeat_seconds: float = 30.0
    poll_seconds: float = 5.0
    max_attempts: int = 3
    allow_copy: bool = True
    verify_loose: bool = False
    verify_existing: bool = True
    memory_bytes: int = 0

    @classmethod
    def from_env(cls, **overrides) -> ApplySettings:
        def need(name: str) -> str:
            v = optional_env(name)
            if not v:
                raise ConfigError(f"{name} is not configured (no default path).")
            return v

        kw = dict(
            v2_root=Path(need("FORGE_V2_ROOT")),
            source_root=Path(need("FORGE_SOURCE_ROOT")),
            scratch=Path(need("FORGE_SCRATCH")),
            shared_mount_ack=optional_env("FORGE_SOURCE_SHARED_MOUNT") == "1",
            caps=Caps.from_env(),
            io_mbps=_env_float("FORGE_MATERIALIZE_IO_MBPS", 0.0),
            stale_seconds=_env_float("FORGE_MATERIALIZE_STALE_SECONDS", 900),
            heartbeat_seconds=_env_float("FORGE_MATERIALIZE_HEARTBEAT_SECONDS", 30),
            poll_seconds=_env_float("FORGE_MATERIALIZE_POLL_SECONDS", 5),
            max_attempts=int(_env_float("FORGE_MATERIALIZE_MAX_ATTEMPTS", 3)),
            memory_bytes=int(_env_float("FORGE_MATERIALIZE_MEMORY_BYTES", 0)),
        )
        kw.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**kw)

    def to_env_dict(self) -> dict:
        d = dict(self.__dict__)
        d["caps"] = self.caps.__dict__
        return {k: (str(v) if isinstance(v, Path) else v) for k, v in d.items()}

    @classmethod
    def from_env_dict(cls, d: dict) -> ApplySettings:
        d = dict(d)
        d["caps"] = Caps(**d["caps"])
        for k in ("v2_root", "source_root", "scratch"):
            d[k] = Path(d[k])
        return cls(**d)


@dataclass
class Scope:
    packs: list[int] | None = None  # None = whole plan
    units: list[int] | None = None


@dataclass
class WorkerStats:
    units: int = 0
    packs: int = 0
    guard_refusals: int = 0
    errors: int = 0
    blob_states: Counter = field(default_factory=Counter)
    pack_states: Counter = field(default_factory=Counter)


# ------------------------------------------------------------------------------- test hooks

_OPS = 0


def _maybe_die() -> None:
    """Test hook: SIGKILL ourselves after N published files (proves resume after a hard kill)."""
    global _OPS
    limit = os.environ.get("FORGE_MATERIALIZE_TEST_KILL_AFTER")
    if not limit:
        return
    _OPS += 1
    if _OPS >= int(limit):
        os.kill(os.getpid(), signal.SIGKILL)


# ----------------------------------------------------------------------------------------- DB


def active_plan_id(engine: Engine) -> int:
    with engine.connect() as conn:
        pid = conn.execute(
            text(
                "SELECT id FROM materialize_plans WHERE status = 'active' ORDER BY id DESC LIMIT 1"
            )
        ).scalar()
    if pid is None:
        raise ConfigError("no active materialize plan — run `forge materialize plan` first")
    return int(pid)


def resolve_scope(
    engine: Engine, plan_id: int, pack_ids: list[int] | None, limit: int | None
) -> Scope:
    if not pack_ids and not limit:
        return Scope()
    with engine.connect() as conn:
        if pack_ids:
            packs = [
                int(r)
                for r in conn.execute(
                    text(
                        "SELECT pack_id FROM materialize_packs WHERE plan_id = :p "
                        "AND pack_id = ANY(CAST(:ids AS bigint[])) ORDER BY pack_id"
                    ),
                    {"p": plan_id, "ids": pack_ids},
                ).scalars()
            ]
            if len(packs) != len(set(pack_ids)):
                missing = sorted(set(pack_ids) - set(packs))
                raise ConfigError(f"packs not in plan {plan_id}: {missing}")
        else:
            packs = [
                int(r)
                for r in conn.execute(
                    text(
                        "SELECT pack_id FROM materialize_packs WHERE plan_id = :p "
                        "AND status NOT IN ('done', 'incomplete') ORDER BY pack_id LIMIT :n"
                    ),
                    {"p": plan_id, "n": limit},
                ).scalars()
            ]
        units = [
            int(r)
            for r in conn.execute(
                text(
                    """
                    SELECT DISTINCT b.unit_id FROM materialize_files f
                    JOIN materialize_blobs b ON b.plan_id = f.plan_id AND b.sha256 = f.sha256
                    WHERE f.plan_id = :p AND f.pack_id = ANY(CAST(:ids AS bigint[]))
                      AND b.unit_id IS NOT NULL
                    """
                ),
                {"p": plan_id, "ids": packs},
            ).scalars()
        ]
    return Scope(packs=packs, units=sorted(units))


def reap(engine: Engine, plan_id: int, stale_seconds: float, max_attempts: int) -> dict:
    """Return stale claims to ``pending`` (or ``failed`` once attempts are exhausted)."""
    out = {}
    with engine.begin() as conn:
        for table, key in (("materialize_units", "id"), ("materialize_packs", "pack_id")):
            rows = conn.execute(
                text(
                    f"""
                    UPDATE {table} SET
                        status = CASE WHEN attempts >= :max THEN 'failed' ELSE 'pending' END,
                        error = CASE WHEN attempts >= :max
                                THEN 'attempts_exhausted (worker died or stalled)'
                                ELSE error END,
                        claimed_by = NULL, claimed_at = NULL
                    WHERE plan_id = :p AND status = 'claimed'
                      AND claimed_at < now() - make_interval(secs => :stale)
                    RETURNING {key}, status
                    """
                ),
                {"p": plan_id, "max": max_attempts, "stale": stale_seconds},
            ).all()
            out[table] = len(rows)
            failed_units = [r[0] for r in rows if table == "materialize_units" and r[1] == "failed"]
            if failed_units:
                conn.execute(
                    text(
                        "UPDATE materialize_blobs SET state = 'failed', "
                        "error = 'unit attempts exhausted', finished_at = now() "
                        "WHERE unit_id = ANY(CAST(:u AS bigint[])) AND state = 'pending'"
                    ),
                    {"u": failed_units},
                )
    return out


def _claim_unit(engine: Engine, plan_id: int, worker: str, scope: Scope):
    with engine.begin() as conn:
        return (
            conn.execute(
                text(
                    """
                UPDATE materialize_units SET status = 'claimed', claimed_by = :w,
                    claimed_at = now(), attempts = attempts + 1, error = NULL
                WHERE id = (
                    SELECT id FROM materialize_units
                    WHERE plan_id = :p AND status = 'pending'
                      AND (CAST(:scope AS bigint[]) IS NULL OR id = ANY(CAST(:scope AS bigint[])))
                    ORDER BY (kind = 'archive'), id
                    LIMIT 1 FOR UPDATE SKIP LOCKED
                )
                RETURNING id, kind, root_container_id, attempts
                """
                ),
                {"p": plan_id, "w": worker, "scope": scope.units},
            )
            .mappings()
            .first()
        )


def _claim_pack(engine: Engine, plan_id: int, worker: str, scope: Scope):
    with engine.begin() as conn:
        return (
            conn.execute(
                text(
                    """
                UPDATE materialize_packs SET status = 'claimed', claimed_by = :w,
                    claimed_at = now(), attempts = attempts + 1, error = NULL
                WHERE (plan_id, pack_id) = (
                    SELECT k.plan_id, k.pack_id FROM materialize_packs k
                    WHERE k.plan_id = :p AND k.status = 'pending'
                      AND (CAST(:scope AS bigint[]) IS NULL
                           OR k.pack_id = ANY(CAST(:scope AS bigint[])))
                      AND NOT EXISTS (
                          SELECT 1 FROM materialize_files f
                          JOIN materialize_blobs b ON b.plan_id = f.plan_id
                                                  AND b.sha256 = f.sha256
                          WHERE f.plan_id = k.plan_id AND f.pack_id = k.pack_id
                            AND b.state = 'pending'
                      )
                    ORDER BY k.pack_id
                    LIMIT 1 FOR UPDATE SKIP LOCKED
                )
                RETURNING pack_id, dir, category, name, attempts, meta
                """
                ),
                {"p": plan_id, "w": worker, "scope": scope.packs},
            )
            .mappings()
            .first()
        )


def _remaining(engine: Engine, plan_id: int, scope: Scope) -> tuple[int, int]:
    with engine.connect() as conn:
        units = conn.execute(
            text(
                "SELECT count(*) FROM materialize_units WHERE plan_id = :p "
                "AND status IN ('pending', 'claimed') "
                "AND (CAST(:s AS bigint[]) IS NULL OR id = ANY(CAST(:s AS bigint[])))"
            ),
            {"p": plan_id, "s": scope.units},
        ).scalar_one()
        packs = conn.execute(
            text(
                "SELECT count(*) FROM materialize_packs WHERE plan_id = :p "
                "AND status IN ('pending', 'claimed') "
                "AND (CAST(:s AS bigint[]) IS NULL OR pack_id = ANY(CAST(:s AS bigint[])))"
            ),
            {"p": plan_id, "s": scope.packs},
        ).scalar_one()
    return int(units), int(packs)


_OWN_UNIT = "id = :id AND claimed_by = :w AND attempts = :a AND status = 'claimed'"
_OWN_PACK = (
    "plan_id = :p AND pack_id = :id AND claimed_by = :w AND attempts = :a AND status = 'claimed'"
)


class Heartbeat(threading.Thread):
    def __init__(self, engine: Engine, plan_id: int, worker: str, interval: float) -> None:
        super().__init__(daemon=True)
        self.engine, self.plan_id, self.worker, self.interval = engine, plan_id, worker, interval
        self.stop = threading.Event()

    def run(self) -> None:
        while not self.stop.wait(self.interval):
            try:
                with self.engine.begin() as conn:
                    for table in ("materialize_units", "materialize_packs"):
                        conn.execute(
                            text(
                                f"UPDATE {table} SET claimed_at = now() WHERE plan_id = :p "
                                "AND status = 'claimed' AND claimed_by = :w"
                            ),
                            {"p": self.plan_id, "w": self.worker},
                        )
            except Exception as exc:  # noqa: BLE001 - heartbeat must never kill the worker
                log("heartbeat_error", worker=self.worker, error=repr(exc)[:200])


# ----------------------------------------------------------------------------------- worker


def _mtime_us(dt: datetime) -> int:
    return (dt - EPOCH) // timedelta(microseconds=1)


def _source_unchanged(path: Path, size: int | None, mtime: datetime | None) -> str | None:
    """``None`` if the source file still matches the catalog, else a reason."""
    try:
        st = os.stat(path, follow_symlinks=False)
    except FileNotFoundError:
        return "source_missing"
    if not stat.S_ISREG(st.st_mode):
        return "source_not_regular"
    if size is not None and st.st_size != size:
        return "source_changed: size"
    if mtime is not None and st.st_mtime_ns // 1000 != _mtime_us(mtime):
        return "source_changed: mtime"
    return None


def _safe_source(root: Path, rel: str) -> Path:
    if not is_v2_relative_safe(rel):
        raise GuardError(f"unsafe catalog source path {rel!r}")
    return root / rel


class Worker:
    def __init__(
        self,
        settings: ApplySettings,
        plan_id: int,
        worker_id: str,
        engine: Engine,
        scope: Scope,
        guard: WriteGuard,
    ) -> None:
        self.s, self.plan_id, self.worker, self.engine, self.scope = (
            settings,
            plan_id,
            worker_id,
            engine,
            scope,
        )
        self.guard = guard
        rate = settings.io_mbps * 1e6 / max(1, settings.procs)
        self.throttle = TokenBucket(rate)
        self.store = BlobStore(guard, allow_copy=settings.allow_copy, throttle=self.throttle)
        self.sevenzip = find_7zz()
        self.stats = WorkerStats()

    # ------------------------------------------------------------------------------ units
    def _unit_blobs(self, unit_id: int) -> list[dict]:
        with self.engine.connect() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    text(
                        """
                        SELECT sha256, size, source_kind, source_path, source_size, source_mtime,
                               member_chain
                        FROM materialize_blobs
                        WHERE plan_id = :p AND unit_id = :u AND state <> 'done'
                        ORDER BY source_path NULLS LAST, sha256
                        """
                    ),
                    {"p": self.plan_id, "u": unit_id},
                ).mappings()
            ]

    def process_unit(self, unit) -> None:
        uid, attempt = int(unit["id"]), int(unit["attempts"])
        blobs = self._unit_blobs(uid)
        tag = f"u{uid}"
        if attempt > 1 and blobs:
            removed = self.store.clean_temps([b["sha256"] for b in blobs], tag)
            if removed:
                log("cleaned_temps", unit=uid, removed=removed)
        if unit["kind"] == "loose":
            results = self._loose(blobs, tag)
        else:
            results = self._archive(int(unit["root_container_id"]), blobs, tag)
        self._finish_unit(uid, attempt, results, None)

    def _loose(self, blobs: list[dict], tag: str) -> dict[str, tuple]:
        results: dict[str, tuple] = {}
        for b in blobs:
            sha, size = b["sha256"], int(b["size"])
            src = _safe_source(self.s.source_root, b["source_path"])
            why = _source_unchanged(src, b["source_size"], b["source_mtime"])
            if why:
                results[sha] = ("failed", None, why)
                continue
            try:
                method = self.store.link_from_source(src, sha, size, tag)
                if self.s.verify_loose:
                    got, n = hash_path(self.store.path(sha), self.throttle)
                    if got != sha or n != size:
                        results[sha] = ("failed", method, f"sha_mismatch: got {got}")
                        continue
                results[sha] = ("done", method, None)
            except (CopyDisabled, StoreCorrupt) as x:
                results[sha] = ("failed", None, f"{type(x).__name__}: {x}"[:500])
            except FileNotFoundError as x:
                results[sha] = ("failed", None, f"source_missing: {x}"[:500])
            _maybe_die()
        return results

    def _archive(self, root_id: int, blobs: list[dict], tag: str) -> dict[str, tuple]:
        results: dict[str, tuple] = {}
        with self.engine.connect() as conn:
            vols = (
                conn.execute(
                    text(
                        """
                    SELECT sf.path, sf.size, sf.mtime, sf.present
                    FROM container_files cf JOIN source_files sf ON sf.id = cf.source_file_id
                    WHERE cf.container_id = :c ORDER BY cf.ordinal
                    """
                    ),
                    {"c": root_id},
                )
                .mappings()
                .all()
            )
            nested = {
                tuple(r["parent_chain"]): r["blob_sha"]
                for r in conn.execute(
                    text(
                        """
                        WITH RECURSIVE d AS (
                            SELECT id, parent_chain, blob_sha FROM containers
                            WHERE parent_container_id = :c
                            UNION ALL
                            SELECT c.id, c.parent_chain, c.blob_sha FROM containers c
                            JOIN d ON c.parent_container_id = d.id
                        )
                        SELECT parent_chain, blob_sha FROM d
                        WHERE parent_chain IS NOT NULL AND blob_sha IS NOT NULL
                        """
                    ),
                    {"c": root_id},
                ).mappings()
            }
        paths = []
        for v in vols:
            p = _safe_source(self.s.source_root, v["path"])
            why = None if v["present"] else "source_missing"
            why = why or _source_unchanged(p, v["size"], v["mtime"])
            if why:
                return {b["sha256"]: ("failed", None, f"{why}: {v['path']}") for b in blobs}
            paths.append(p)
        if not paths:
            return {b["sha256"]: ("failed", None, "container has no source files") for b in blobs}
        wants = {}
        for b in blobs:
            sha, size = b["sha256"], int(b["size"])
            if self.store.has(sha, size):
                results[sha] = ("done", "existing", None)
                continue
            wants[tuple(b["member_chain"])] = Want(sha, size)
        if wants:
            ex = Extractor(
                self.guard,
                self.store,
                scratch=self.s.scratch,
                caps=self.s.caps,
                tag=tag,
                sevenzip=self.sevenzip,
                throttle=self.throttle,
            )
            for sha, o in ex.run(paths, wants, nested).items():
                results[sha] = (o.state, o.method, o.error)
                _maybe_die()
        return results

    def _finish_unit(self, uid: int, attempt: int, results: dict, error: str | None) -> None:
        with self.engine.begin() as conn:
            owned = conn.execute(
                text(f"SELECT 1 FROM materialize_units WHERE {_OWN_UNIT} FOR UPDATE"),
                {"id": uid, "w": self.worker, "a": attempt},
            ).first()
            if not owned:
                log("lost_claim", unit=uid, worker=self.worker)
                return
            if results:
                conn.execute(
                    text(
                        """
                        UPDATE materialize_blobs SET state = :st, method = :m, error = :e,
                            finished_at = now()
                        WHERE plan_id = :p AND sha256 = :sha
                        """
                    ),
                    [
                        {"p": self.plan_id, "sha": sha, "st": st, "m": m, "e": e}
                        for sha, (st, m, e) in results.items()
                    ],
                )
            conn.execute(
                text(
                    "UPDATE materialize_units SET status = 'done', finished_at = now(), "
                    f"error = :e WHERE {_OWN_UNIT}"
                ),
                {"id": uid, "w": self.worker, "a": attempt, "e": error},
            )
        for st, _, _ in results.values():
            self.stats.blob_states[st] += 1
        self.stats.units += 1

    def _fail_claim(self, table: str, key: int, attempt: int, error: str) -> None:
        own = _OWN_UNIT if table == "materialize_units" else _OWN_PACK
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    f"""
                    UPDATE {table} SET
                        status = CASE WHEN attempts >= :max THEN 'failed' ELSE 'pending' END,
                        error = :e, claimed_by = NULL, claimed_at = NULL
                    WHERE {own} RETURNING status
                    """
                ),
                {
                    "p": self.plan_id,
                    "id": key,
                    "w": self.worker,
                    "a": attempt,
                    "e": error[:1000],
                    "max": self.s.max_attempts,
                },
            ).first()
            if row and row[0] == "failed" and table == "materialize_units":
                conn.execute(
                    text(
                        "UPDATE materialize_blobs SET state = 'failed', error = :e, "
                        "finished_at = now() WHERE unit_id = :u AND state = 'pending'"
                    ),
                    {"u": key, "e": ("unit failed: " + error)[:1000]},
                )

    # ------------------------------------------------------------------------------ packs
    def process_pack(self, pack) -> None:
        pid, attempt = int(pack["pack_id"]), int(pack["attempts"])
        pdir = pack["dir"]
        base = join_v2(self.guard, pdir)
        with self.engine.connect() as conn:
            files = [
                dict(r)
                for r in conn.execute(
                    text(
                        """
                        SELECT f.rel_path, f.sha256, f.size, f.kind, f.container_id,
                               f.anchor_path, f.member_chain, b.state, b.source_kind,
                               b.source_path, b.root_container_id, b.member_chain AS src_chain,
                               b.error AS blob_error
                        FROM materialize_files f
                        JOIN materialize_blobs b ON b.plan_id = f.plan_id AND b.sha256 = f.sha256
                        WHERE f.plan_id = :p AND f.pack_id = :id
                        ORDER BY f.rel_path
                        """
                    ),
                    {"p": self.plan_id, "id": pid},
                ).mappings()
            ]
        targets = [join_v2(self.guard, f"{pdir}/{f['rel_path']}") for f in files]
        if attempt > 1:
            self._clean_pack_temps(sorted({t.parent for t in targets}))
        self.guard.mkdirs(base)
        counts: Counter = Counter()
        missing = []
        for f, target in zip(files, targets, strict=True):
            if f["state"] != "done":
                missing.append(
                    {"path": f["rel_path"], "sha256": f["sha256"], "reason": f["blob_error"]}
                )
                continue
            how = self.store.place(
                f["sha256"], int(f["size"]), target, verify_existing=self.s.verify_existing
            )
            counts[how] += 1
            if how != "skipped":
                _maybe_die()
        dp = datapackage(pack, files, missing, self.plan_id)
        counts["datapackage"] = int(self._write_datapackage(base / DATAPACKAGE, dp))
        status = "done" if not missing else "incomplete"
        with self.engine.begin() as conn:
            n = conn.execute(
                text(
                    f"""
                    UPDATE materialize_packs SET status = :st, finished_at = now(),
                        missing = :m, counts = :c, error = NULL
                    WHERE {_OWN_PACK}
                    """
                ),
                {
                    "p": self.plan_id,
                    "id": pid,
                    "w": self.worker,
                    "a": attempt,
                    "st": status,
                    "m": len(missing),
                    "c": json.dumps(dict(counts), sort_keys=True),
                },
            ).rowcount
        if not n:
            log("lost_claim", pack=pid, worker=self.worker)
        self.stats.packs += 1
        self.stats.pack_states[status] += 1

    def _clean_pack_temps(self, dirs: list[Path]) -> None:
        for d in dirs:
            try:
                names = os.listdir(d)
            except FileNotFoundError:
                continue
            for name in names:
                if name.startswith(".forge-tmp-"):
                    try:
                        self.guard.unlink(d / name)
                    except FileNotFoundError:
                        pass

    def _write_datapackage(self, path: Path, dp: dict) -> bool:
        """Write ``datapackage.json`` unless an identical one (ignoring ``materialized_at``)
        exists. Returns True when written."""
        try:
            fd = WriteGuard.open_read(path)
        except FileNotFoundError:
            fd = None
        if fd is not None:
            try:
                chunks = []
                while True:
                    data = os.read(fd, 1 << 20)
                    if not data:
                        break
                    chunks.append(data)
            finally:
                os.close(fd)
            try:
                old = json.loads(b"".join(chunks))
                if _strip_volatile(old) == _strip_volatile(dp):
                    return False
            except ValueError:
                pass
        body = (json.dumps(dp, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
        tmp = self.guard.new_temp_name(path.parent, ".forge-tmp-")
        w = TempWriter(self.guard, tmp)
        try:
            w.write(body)
            w.close()
        except BaseException:
            w.abort()
            raise
        self.guard.rename(tmp, path)
        return True

    # ------------------------------------------------------------------------------- loop
    def run(self) -> WorkerStats:
        hb = Heartbeat(self.engine, self.plan_id, self.worker, self.s.heartbeat_seconds)
        hb.start()
        next_reap = 0.0
        try:
            while True:
                if time.monotonic() >= next_reap:
                    r = reap(self.engine, self.plan_id, self.s.stale_seconds, self.s.max_attempts)
                    if any(r.values()):
                        log("reaped", worker=self.worker, **r)
                    next_reap = time.monotonic() + max(self.s.poll_seconds, 1.0)
                unit = _claim_unit(self.engine, self.plan_id, self.worker, self.scope)
                if unit is not None:
                    self._guarded("materialize_units", int(unit["id"]), unit, self.process_unit)
                    continue
                pack = _claim_pack(self.engine, self.plan_id, self.worker, self.scope)
                if pack is not None:
                    self._guarded(
                        "materialize_packs", int(pack["pack_id"]), pack, self.process_pack
                    )
                    continue
                units, packs = _remaining(self.engine, self.plan_id, self.scope)
                if units == 0 and packs == 0:
                    break
                time.sleep(self.s.poll_seconds)
        finally:
            hb.stop.set()
        return self.stats

    def _guarded(self, table: str, key: int, row, fn) -> None:
        t0 = time.monotonic()
        try:
            fn(row)
            log(
                "finished",
                table=table,
                id=key,
                worker=self.worker,
                seconds=round(time.monotonic() - t0, 3),
            )
        except GuardError as x:
            # A write was aimed outside v2 (or into the source tree) and was refused. Record it,
            # keep going with other work, and make the process exit non-zero.
            self.stats.guard_refusals += 1
            log("GUARD_REFUSED", table=table, id=key, worker=self.worker, error=str(x)[:500])
            self._fail_claim(table, key, int(row["attempts"]), f"guard_refused: {x}")
        except Exception as x:  # noqa: BLE001 - one unit/pack must not stop the worker
            self.stats.errors += 1
            log("error", table=table, id=key, worker=self.worker, error=repr(x)[:500])
            self._fail_claim(table, key, int(row["attempts"]), repr(x))


def _strip_volatile(dp: dict) -> dict:
    d = json.loads(json.dumps(dp))
    d.get("forge", {}).pop("materialized_at", None)
    return d


def datapackage(pack, files: list[dict], missing: list[dict], plan_id: int) -> dict:
    """Frictionless-style ``datapackage.json`` with forge provenance for every file."""
    meta = json.loads(pack["meta"] or "{}")
    name = (pack["name"] or f"pack-{pack['pack_id']}").strip()
    slug = "".join(c if c.isalnum() or c in "-._" else "-" for c in name.lower()).strip("-.")
    resources = []
    for f in files:
        if f["state"] != "done":
            continue
        if f["source_kind"] == "loose":
            source = {"kind": "loose", "path": f["source_path"]}
        else:
            source = {
                "kind": "archive",
                "container_id": f["root_container_id"],
                "member_chain": list(f["src_chain"] or []),
            }
        resources.append(
            {
                "path": f["rel_path"],
                "bytes": int(f["size"]),
                "hash": f"sha256:{f['sha256']}",
                "forge_kind": f["kind"],
                "provenance": {
                    "container_id": f["container_id"],
                    "source_path": f["anchor_path"],
                    "member_chain": list(f["member_chain"] or []),
                },
                "materialized_from": source,
            }
        )
    keywords = pack_keywords(
        category=pack["category"],
        source_tag=meta.get("source_tag"),
        creator=meta.get("creator"),
        tags=meta.get("tags"),
        tagged=bool(meta.get("tagged", False)),
    )
    return {
        "name": slug or f"pack-{pack['pack_id']}",
        "title": name,
        "category": pack["category"],
        "creator": meta.get("creator"),
        "source": meta.get("source_tag"),
        "keywords": keywords,
        "resources": resources,
        "forge": {
            "pack_id": int(pack["pack_id"]),
            "plan_id": plan_id,
            "tool": "library-forge",
            "tool_version": __version__,
            "materialized_at": datetime.now(UTC).isoformat(),
            "needs_review": meta.get("needs_review", False),
            "classified": meta.get("classified", True),
            "pack_status": meta.get("pack_status"),
            "source_containers": meta.get("containers", []),
            "source_loose_units": meta.get("loose_units", []),
            "blob_shas": sorted({f["sha256"] for f in files}),
            "missing": missing,
        },
    }


# ------------------------------------------------------------------------------- entrypoint


def _set_memory_limit(nbytes: int) -> None:
    if nbytes > 0:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (nbytes, nbytes))


def _child_main(sdict: dict, plan_id: int, worker_id: str, db_url: str, scope: Scope) -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    settings = ApplySettings.from_env_dict(sdict)
    stats = run_worker(settings, plan_id, worker_id, db_url, scope)
    sys.exit(3 if stats.guard_refusals else (1 if stats.errors else 0))


def run_worker(
    settings: ApplySettings, plan_id: int, worker_id: str, db_url: str, scope: Scope
) -> WorkerStats:
    _set_memory_limit(settings.memory_bytes)
    guard, report = open_guard(
        settings.v2_root,
        settings.source_root,
        settings.scratch,
        shared_mount_ack=settings.shared_mount_ack,
    )
    engine = create_engine(db_url, pool_pre_ping=True, pool_size=2, max_overflow=2)
    try:
        log("worker_start", worker=worker_id, plan=plan_id, pid=os.getpid(), **report.to_dict())
        stats = Worker(settings, plan_id, worker_id, engine, scope, guard).run()
        log(
            "worker_stop",
            worker=worker_id,
            units=stats.units,
            packs=stats.packs,
            errors=stats.errors,
            guard_refusals=stats.guard_refusals,
            blobs=dict(stats.blob_states),
            pack_states=dict(stats.pack_states),
            writes=guard.writes,
        )
        return stats
    finally:
        engine.dispose()


def main_apply(
    settings: ApplySettings,
    db_url: str,
    *,
    plan_id: int | None = None,
    pack_ids: list[int] | None = None,
    limit: int | None = None,
    resume: bool = False,
    retry_failed: bool = False,
    worker_id: str | None = None,
) -> int:
    # Fail fast on an unsafe layout before touching the DB queue.
    open_guard(
        settings.v2_root,
        settings.source_root,
        settings.scratch,
        shared_mount_ack=settings.shared_mount_ack,
    )
    engine = create_engine(db_url, pool_pre_ping=True)
    try:
        pid = plan_id or active_plan_id(engine)
        if resume:
            # Only safe when no other apply is running: every claim is treated as dead.
            r = reap(engine, pid, 0, settings.max_attempts + 1)
            log("resume_reaped", plan=pid, **r)
        if retry_failed:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE materialize_units SET status = 'pending', attempts = 0, "
                        "error = NULL WHERE plan_id = :p AND status = 'failed'"
                    ),
                    {"p": pid},
                )
                conn.execute(
                    text(
                        "UPDATE materialize_blobs SET state = 'pending', error = NULL "
                        "WHERE plan_id = :p AND state = 'failed'"
                    ),
                    {"p": pid},
                )
                conn.execute(
                    text(
                        "UPDATE materialize_packs SET status = 'pending', attempts = 0, "
                        "error = NULL WHERE plan_id = :p AND status IN ('failed', 'incomplete')"
                    ),
                    {"p": pid},
                )
        scope = resolve_scope(engine, pid, pack_ids, limit)
    finally:
        engine.dispose()
    base = worker_id or optional_env("FORGE_WORKER_ID") or socket.gethostname()
    if settings.procs <= 1:
        stats = run_worker(settings, pid, f"{base}-0", db_url, scope)
        return 3 if stats.guard_refusals else (1 if stats.errors else 0)
    ctx = multiprocessing.get_context("spawn")
    procs = [
        ctx.Process(
            target=_child_main,
            args=(settings.to_env_dict(), pid, f"{base}-{i}", db_url, scope),
            name=f"materialize-{i}",
        )
        for i in range(settings.procs)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    codes = [p.exitcode for p in procs]
    log("apply_done", plan=pid, exit_codes=codes)
    if any(c == 3 for c in codes):
        return 3
    return 0 if all(c == 0 for c in codes) else 1
