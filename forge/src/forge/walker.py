"""Source inventory walker. Seeds containers; does not hash loose files.

INIT-032/SPEC-005 — hashing is SPEC-007 via the engine (loose_batch workers).
"""

from __future__ import annotations

import json
import os
import queue
import re
import threading
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection, Engine

from forge.config import ConfigError, ForgeConfig, normalize_db_url, skip_dir_names
from forge.db.enums import (
    ContainerKind,
    ContainerStatus,
    FailureReason,
    SourceFileKind,
    SweepKind,
)

DEFAULT_THREADS = 8
FLUSH_EVERY = 10_000
LOOSE_BATCH_MAX_FILES = 500
LOOSE_BATCH_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
ARCHIVE_DEPTH = 1
LOOSE_BATCH_DEPTH = 0

# Longer suffixes first so .tar.gz wins over .gz for extension sniffing.
_ARCHIVE_SUFFIXES: tuple[str, ...] = (
    ".tar.gz",
    ".tar.bz2",
    ".tar.xz",
    ".tgz",
    ".tar",
    ".zip",
    ".rar",
    ".7z",
    ".cbz",
    ".cbr",
    ".gz",
    ".bz2",
    ".xz",
)

# Longer magics first (rar5 before rar4).
_MAGICS: tuple[tuple[bytes, str], ...] = (
    (b"Rar!\x1a\x07\x01\x00", "rar5"),
    (b"Rar!\x1a\x07\x00", "rar4"),
    (b"7z\xbc\xaf'\x1c", "7z"),
    (b"\xfd7zXZ\x00", "xz"),
    (b"PK\x03\x04", "zip"),
    (b"PK\x05\x06", "zip"),
    (b"PK\x07\x08", "zip"),
    (b"\x1f\x8b", "gzip"),
    (b"BZh", "bzip2"),
)

_RE_EXT_NNN = re.compile(r"^(?P<base>.+)\.(?P<ext>7z|zip)\.(?P<num>\d{3})$", re.IGNORECASE)
_RE_PART = re.compile(r"^(?P<base>.+)\.part(?P<num>\d+)\.(?P<ext>rar|zip|7z)$", re.IGNORECASE)
_RE_RNN = re.compile(r"^(?P<base>.+)\.r(?P<num>\d{2})$", re.IGNORECASE)
_RE_ZNN = re.compile(r"^(?P<base>.+)\.z(?P<num>\d{2})$", re.IGNORECASE)
_RE_NNN = re.compile(r"^(?P<base>.+)\.(?P<num>\d{3})$", re.IGNORECASE)

_O_RDONLY_NOFOLLOW = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


@dataclass(frozen=True)
class WalkFile:
    """One present source file. path is relative to FORGE_SOURCE_ROOT (posix, unique)."""

    path: str
    size: int
    mtime_ns: int
    kind: SourceFileKind
    format: str | None
    volume_set: str | None = None
    volume_ordinal: int | None = None  # 1-based among the container's files


@dataclass(frozen=True)
class ArchiveGroup:
    """One archive container to seed (single file or a volume set)."""

    volume_set: str | None
    files: tuple[WalkFile, ...]
    format: str | None
    missing_volume: bool


@dataclass(frozen=True)
class LooseBatch:
    """One loose_batch container: <= 500 files and <= 2 GiB, directory order."""

    files: tuple[WalkFile, ...]
    bytes: int


@dataclass
class WalkCounts:
    files: int = 0
    dirs: int = 0
    bytes: int = 0
    archives: int = 0
    loose: int = 0
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    vanished: int = 0
    containers_seeded: int = 0
    symlinks: int = 0
    skipped_dirs: int = 0
    errors: int = 0


@dataclass(frozen=True)
class WalkResult:
    sweep_id: int | None
    counts: WalkCounts
    dry_run: bool


@dataclass(frozen=True)
class _VolumePart:
    base: str
    scheme: str
    ordinal: int


def datetime_from_mtime_ns(mtime_ns: int) -> datetime:
    """UTC timestamp at microsecond precision (Postgres timestamptz)."""
    sec, nsec = divmod(int(mtime_ns), 1_000_000_000)
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=sec, microseconds=nsec // 1000)


def format_counts(counts: WalkCounts) -> str:
    rows = (
        ("files", counts.files),
        ("dirs", counts.dirs),
        ("bytes", counts.bytes),
        ("archives", counts.archives),
        ("loose", counts.loose),
        ("new", counts.new),
        ("changed", counts.changed),
        ("unchanged", counts.unchanged),
        ("vanished", counts.vanished),
        ("containers_seeded", counts.containers_seeded),
        ("symlinks", counts.symlinks),
        ("skipped_dirs", counts.skipped_dirs),
        ("errors", counts.errors),
    )
    return "\n".join(f"{name}\t{value}" for name, value in rows)


def parse_volume(filename: str) -> _VolumePart | None:
    """Return a split-volume identity, or None if this is not a continuation name."""
    match = _RE_EXT_NNN.match(filename)
    if match:
        return _VolumePart(match["base"], "extnnn", int(match["num"]))
    match = _RE_PART.match(filename)
    if match:
        return _VolumePart(match["base"], "part", int(match["num"]))
    match = _RE_RNN.match(filename)
    if match:
        return _VolumePart(match["base"], "r", int(match["num"]))
    match = _RE_ZNN.match(filename)
    if match:
        return _VolumePart(match["base"], "z", int(match["num"]))
    match = _RE_NNN.match(filename)
    if match:
        return _VolumePart(match["base"], "nnn", int(match["num"]))
    return None


def is_archive_candidate(filename: str) -> bool:
    if parse_volume(filename) is not None:
        return True
    lower = filename.lower()
    return any(lower.endswith(suffix) for suffix in _ARCHIVE_SUFFIXES)


def _read_magic(path: str, n: int = 16, offset: int = 0) -> bytes:
    """Read n bytes at offset. O_RDONLY only; never follows a final symlink."""
    fd = os.open(path, _O_RDONLY_NOFOLLOW)
    try:
        if offset:
            os.lseek(fd, offset, os.SEEK_SET)
        return os.read(fd, n)
    finally:
        os.close(fd)


def sniff_format(path: str, *, extension: str) -> str | None:
    """Sniff archive magic. 8–16 bytes; tar also reads 8 bytes at offset 257."""
    try:
        head = _read_magic(path, 16, 0)
    except OSError:
        return None
    for magic, name in _MAGICS:
        if head.startswith(magic):
            return name
    ext = extension.lower()
    if ext == ".tar" or ext.endswith(".tar"):
        try:
            ustar = _read_magic(path, 8, 257)
        except OSError:
            return None
        if ustar.startswith(b"ustar"):
            return "tar"
    return None


def _rel_dir(relpath: str) -> str:
    directory = relpath.rsplit("/", 1)[0] if "/" in relpath else ""
    return directory


def _volume_set_key(directory: str, base: str, scheme: str) -> str:
    if directory:
        return f"{directory}/{base}|{scheme}"
    return f"{base}|{scheme}"


def _lead_schemes(filename: str) -> list[tuple[str, str, int]]:
    """Possible (base, scheme, sort_key) if this file can lead a sibling set."""
    lower = filename.lower()
    out: list[tuple[str, str, int]] = []
    if parse_volume(filename) is not None:
        return out
    if lower.endswith(".rar"):
        out.append((filename[: -len(".rar")], "r", -1))
    elif lower.endswith(".cbr"):
        out.append((filename[: -len(".cbr")], "r", -1))
    if lower.endswith(".zip"):
        out.append((filename[: -len(".zip")], "z", -1))
        out.append((filename[: -len(".zip")], "extnnn", 0))
    elif lower.endswith(".cbz"):
        out.append((filename[: -len(".cbz")], "z", -1))
    if lower.endswith(".7z"):
        out.append((filename[: -len(".7z")], "extnnn", 0))
    return out


def _set_incomplete(scheme: str, sort_keys: Sequence[int]) -> bool:
    keys = sorted(set(sort_keys))
    if not keys:
        return True
    if scheme == "part":
        if 1 not in keys:
            return True
        return keys != list(range(1, keys[-1] + 1))
    if scheme in {"nnn", "extnnn"}:
        vols = [k for k in keys if k >= 1]
        if 1 not in vols:
            return True
        return vols != list(range(1, vols[-1] + 1))
    if scheme == "r":
        rest = [k for k in keys if k >= 0]
        if -1 in keys:
            return bool(rest) and rest != list(range(0, rest[-1] + 1))
        if 0 not in rest:
            return True
        return rest != list(range(0, rest[-1] + 1))
    if scheme == "z":
        rest = [k for k in keys if k >= 1]
        if -1 in keys:
            return bool(rest) and rest != list(range(1, rest[-1] + 1))
        if 1 not in rest:
            return True
        return rest != list(range(1, rest[-1] + 1))
    return False


def group_archive_sets(files: Sequence[WalkFile]) -> tuple[list[WalkFile], list[ArchiveGroup]]:
    """Group archive files. A set is >= 2 sibling volumes with the same base.

    Lone ``*.partN.rar`` files (typical: folder named *.partN holding one rar)
    stay single-volume archives. A gap or a missing first volume marks the set
    ``missing_volume``. Returns (all files with volume fields filled, groups).
    """
    archives = [f for f in files if f.kind is SourceFileKind.archive]
    loose = [f for f in files if f.kind is SourceFileKind.loose]
    buckets: dict[tuple[str, str, str], list[tuple[int, WalkFile]]] = defaultdict(list)
    unparsed: list[WalkFile] = []
    for rec in archives:
        name = rec.path.rsplit("/", 1)[-1]
        parsed = parse_volume(name)
        if parsed is None:
            unparsed.append(rec)
            continue
        key = (_rel_dir(rec.path), parsed.base, parsed.scheme)
        buckets[key].append((parsed.ordinal, rec))

    singles: list[WalkFile] = []
    for rec in unparsed:
        name = rec.path.rsplit("/", 1)[-1]
        directory = _rel_dir(rec.path)
        attached = False
        for base, scheme, ordinal in _lead_schemes(name):
            key = (directory, base, scheme)
            if key in buckets:
                buckets[key].append((ordinal, rec))
                attached = True
                break
        if not attached:
            singles.append(rec)

    groups: list[ArchiveGroup] = []
    annotated: list[WalkFile] = []
    for (directory, base, scheme), members in buckets.items():
        if len(members) < 2:
            singles.extend(rec for _, rec in members)
            continue
        members.sort(key=lambda item: item[0])
        incomplete = _set_incomplete(scheme, [ord_ for ord_, _ in members])
        key = _volume_set_key(directory, base, scheme)
        updated: list[WalkFile] = []
        for index, (_, rec) in enumerate(members, start=1):
            updated.append(replace(rec, volume_set=key, volume_ordinal=index))
        groups.append(
            ArchiveGroup(
                volume_set=key,
                files=tuple(updated),
                format=updated[0].format,
                missing_volume=incomplete,
            )
        )
        annotated.extend(updated)

    for rec in singles:
        one = replace(rec, volume_set=None, volume_ordinal=1)
        annotated.append(one)
        groups.append(
            ArchiveGroup(
                volume_set=None,
                files=(one,),
                format=one.format,
                missing_volume=False,
            )
        )

    return annotated + loose, groups


def iter_loose_batches(files: Sequence[WalkFile]) -> list[LooseBatch]:
    """Batch loose files by path order. Caps: 500 files and 2 GiB."""
    loose = sorted(
        (f for f in files if f.kind is SourceFileKind.loose),
        key=lambda rec: rec.path,
    )
    batches: list[LooseBatch] = []
    current: list[WalkFile] = []
    current_bytes = 0
    for rec in loose:
        would_files = len(current) + 1
        would_bytes = current_bytes + rec.size
        if current and (would_files > LOOSE_BATCH_MAX_FILES or would_bytes > LOOSE_BATCH_MAX_BYTES):
            batches.append(LooseBatch(tuple(current), current_bytes))
            current = []
            current_bytes = 0
        current.append(rec)
        current_bytes += rec.size
    if current:
        batches.append(LooseBatch(tuple(current), current_bytes))
    return batches


def classify_file(root: str, abs_path: str, size: int, mtime_ns: int) -> WalkFile:
    rel = os.path.relpath(abs_path, root).replace(os.sep, "/")
    name = os.path.basename(abs_path)
    if not is_archive_candidate(name):
        return WalkFile(rel, size, mtime_ns, SourceFileKind.loose, None)
    ext = os.path.splitext(name)[1]
    if name.lower().endswith(".tar"):
        ext = ".tar"
    fmt = sniff_format(abs_path, extension=ext)
    return WalkFile(rel, size, mtime_ns, SourceFileKind.archive, fmt)


def walk_tree(
    root: str | os.PathLike[str],
    *,
    threads: int = DEFAULT_THREADS,
    skip_dirs: frozenset[str] | None = None,
) -> tuple[list[WalkFile], WalkCounts]:
    """Multi-threaded os.scandir walk. Never follows symlinks."""
    if threads < 1:
        raise ConfigError("--threads must be >= 1")
    root_s = os.path.abspath(os.fspath(root))
    if not os.path.isdir(root_s) or os.path.islink(root_s):
        raise ConfigError(f"FORGE_SOURCE_ROOT is not a directory: {root_s}")
    skip = skip_dirs if skip_dirs is not None else skip_dir_names()
    work: queue.Queue[str | None] = queue.Queue()
    work.put(root_s)
    pending = [1]
    lock = threading.Lock()
    files: list[WalkFile] = []
    counts = WalkCounts()

    def pending_done() -> None:
        pending[0] -= 1
        if pending[0] == 0:
            for _ in range(threads):
                work.put(None)

    def worker() -> None:
        while True:
            directory = work.get()
            if directory is None:
                return
            buf: list[tuple[str, object]] = []
            extra_dirs: list[str] = []
            try:
                with os.scandir(directory) as iterator:
                    for entry in iterator:
                        try:
                            if entry.is_symlink():
                                buf.append(("symlink", entry.path))
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                if entry.name in skip:
                                    buf.append(("skipdir", entry.path))
                                    continue
                                extra_dirs.append(entry.path)
                                buf.append(("dir", entry.path))
                            elif entry.is_file(follow_symlinks=False):
                                stat = entry.stat(follow_symlinks=False)
                                rec = classify_file(
                                    root_s, entry.path, stat.st_size, stat.st_mtime_ns
                                )
                                buf.append(("file", rec))
                            else:
                                buf.append(("other", entry.path))
                        except OSError:
                            buf.append(("error", entry.path))
            except OSError:
                buf.append(("error", directory))
            with lock:
                for kind, payload in buf:
                    if kind == "file":
                        rec = payload
                        assert isinstance(rec, WalkFile)
                        files.append(rec)
                        counts.files += 1
                        counts.bytes += rec.size
                        if rec.kind is SourceFileKind.archive:
                            counts.archives += 1
                        else:
                            counts.loose += 1
                    elif kind == "dir":
                        counts.dirs += 1
                    elif kind == "symlink":
                        counts.symlinks += 1
                    elif kind == "skipdir":
                        counts.skipped_dirs += 1
                    elif kind == "error":
                        counts.errors += 1
                for child in extra_dirs:
                    pending[0] += 1
                    work.put(child)
                pending_done()

    workers = [threading.Thread(target=worker, name=f"forge-walk-{i}") for i in range(threads)]
    for thread in workers:
        thread.start()
    for thread in workers:
        thread.join()
    return files, counts


def _exec_chunked(
    conn: Connection, statement, rows: Sequence[dict], size: int = FLUSH_EVERY
) -> None:
    if not rows:
        return
    for index in range(0, len(rows), size):
        conn.execute(statement, list(rows[index : index + size]))


def _reset_container(
    conn: Connection,
    container_id: int,
    *,
    status: str,
    failure: str | None,
    source_file_id: int | None,
    fmt: str | None,
) -> None:
    conn.execute(text("DELETE FROM occurrences WHERE container_id = :cid"), {"cid": container_id})
    conn.execute(
        text(
            """
            UPDATE containers SET
                status = CAST(:status AS container_status),
                failure_reason = CAST(:failure AS failure_reason),
                source_file_id = :sid,
                format = :fmt,
                attempts = 0,
                claimed_by = NULL,
                claimed_at = NULL,
                members = 0,
                bytes_read = 0
            WHERE id = :cid
            """
        ),
        {
            "cid": container_id,
            "status": status,
            "failure": failure,
            "sid": source_file_id,
            "fmt": fmt,
        },
    )


def _replace_container_files(conn: Connection, container_id: int, file_ids: Sequence[int]) -> None:
    conn.execute(
        text("DELETE FROM container_files WHERE container_id = :cid"),
        {"cid": container_id},
    )
    if not file_ids:
        return
    _exec_chunked(
        conn,
        text(
            """
            INSERT INTO container_files (container_id, source_file_id, ordinal)
            VALUES (:cid, :sid, :ord)
            """
        ),
        [
            {"cid": container_id, "sid": source_file_id, "ord": ordinal}
            for ordinal, source_file_id in enumerate(file_ids, start=1)
        ],
    )


def _insert_container(
    conn: Connection,
    *,
    source_file_id: int | None,
    kind: str,
    fmt: str | None,
    depth: int,
    status: str,
    failure: str | None,
    file_ids: Sequence[int],
) -> int:
    container_id = conn.execute(
        text(
            """
            INSERT INTO containers (
                source_file_id, kind, format, depth, status, failure_reason
            ) VALUES (
                :sid,
                CAST(:kind AS container_kind),
                :fmt,
                :depth,
                CAST(:status AS container_status),
                CAST(:failure AS failure_reason)
            )
            RETURNING id
            """
        ),
        {
            "sid": source_file_id,
            "kind": kind,
            "fmt": fmt,
            "depth": depth,
            "status": status,
            "failure": failure,
        },
    ).scalar_one()
    _replace_container_files(conn, container_id, file_ids)
    return int(container_id)


def _archive_status(group: ArchiveGroup) -> tuple[str, str | None]:
    if group.missing_volume:
        return ContainerStatus.failed.value, FailureReason.missing_volume.value
    return ContainerStatus.pending.value, None


def _sync_archive_groups(
    conn: Connection,
    groups: Sequence[ArchiveGroup],
    path_to_id: dict[str, int],
    changed_paths: set[str],
    new_paths: set[str],
) -> int:
    seeded = 0
    if not groups:
        return 0
    all_ids = [path_to_id[rec.path] for group in groups for rec in group.files]
    membership: dict[int, list[tuple[int, int]]] = defaultdict(list)
    kind_by_cid: dict[int, str] = {}
    if all_ids:
        rows = conn.execute(
            text(
                """
                SELECT cf.container_id, cf.source_file_id, cf.ordinal, c.kind::text
                FROM container_files cf
                JOIN containers c ON c.id = cf.container_id
                WHERE cf.source_file_id IN :ids
                """
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": all_ids},
        ).all()
        for container_id, source_file_id, ordinal, kind in rows:
            kind_by_cid[int(container_id)] = kind
            membership[int(source_file_id)].append((int(container_id), int(ordinal)))

    for group in groups:
        file_ids = [path_to_id[rec.path] for rec in group.files]
        status, failure = _archive_status(group)
        first_id = file_ids[0]
        existing: set[int] = set()
        for sid in file_ids:
            for cid, _ord in membership.get(sid, ()):
                if kind_by_cid.get(cid) == ContainerKind.archive.value:
                    existing.add(cid)
        any_changed = any(rec.path in changed_paths or rec.path in new_paths for rec in group.files)
        expected = [(sid, index) for index, sid in enumerate(file_ids, start=1)]
        if len(existing) == 1:
            cid = next(iter(existing))
            current = conn.execute(
                text(
                    """
                    SELECT source_file_id, ordinal FROM container_files
                    WHERE container_id = :cid ORDER BY ordinal
                    """
                ),
                {"cid": cid},
            ).all()
            current_pairs = [(int(sid), int(ord_)) for sid, ord_ in current]
            membership_same = current_pairs == expected
            if membership_same and not any_changed:
                continue
            if not membership_same:
                _replace_container_files(conn, cid, file_ids)
            _reset_container(
                conn,
                cid,
                status=status,
                failure=failure,
                source_file_id=first_id,
                fmt=group.format,
            )
            seeded += 1
            continue
        if len(existing) == 0:
            _insert_container(
                conn,
                source_file_id=first_id,
                kind=ContainerKind.archive.value,
                fmt=group.format,
                depth=ARCHIVE_DEPTH,
                status=status,
                failure=failure,
                file_ids=file_ids,
            )
            seeded += 1
            continue
        keep = min(existing)
        extras = [cid for cid in existing if cid != keep]
        _replace_container_files(conn, keep, file_ids)
        _reset_container(
            conn,
            keep,
            status=status,
            failure=failure,
            source_file_id=first_id,
            fmt=group.format,
        )
        for extra in extras:
            conn.execute(text("DELETE FROM occurrences WHERE container_id = :cid"), {"cid": extra})
            conn.execute(
                text(
                    """
                    DELETE FROM container_files
                    WHERE container_id = :cid AND source_file_id IN :ids
                    """
                ).bindparams(bindparam("ids", expanding=True)),
                {"cid": extra, "ids": file_ids},
            )
            leftover = conn.execute(
                text("SELECT 1 FROM container_files WHERE container_id = :cid LIMIT 1"),
                {"cid": extra},
            ).first()
            packed = conn.execute(
                text("SELECT 1 FROM pack_containers WHERE container_id = :cid LIMIT 1"),
                {"cid": extra},
            ).first()
            if leftover is None and packed is None:
                conn.execute(text("DELETE FROM containers WHERE id = :cid"), {"cid": extra})
        seeded += 1
    return seeded


def _sync_loose_batches(
    conn: Connection,
    files: Sequence[WalkFile],
    path_to_id: dict[str, int],
    changed_paths: set[str],
) -> int:
    loose = [rec for rec in files if rec.kind is SourceFileKind.loose]
    if not loose:
        return 0
    seeded = 0
    loose_ids = [path_to_id[rec.path] for rec in loose]
    owned = conn.execute(
        text(
            """
            SELECT cf.source_file_id, cf.container_id
            FROM container_files cf
            JOIN containers c ON c.id = cf.container_id
            WHERE c.kind = 'loose_batch' AND cf.source_file_id IN :ids
            """
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": loose_ids},
    ).all()
    sf_to_cid = {int(sid): int(cid) for sid, cid in owned}
    reset_cids: set[int] = set()
    for rec in loose:
        if rec.path in changed_paths:
            cid = sf_to_cid.get(path_to_id[rec.path])
            if cid is not None:
                reset_cids.add(cid)
    for cid in reset_cids:
        first = conn.execute(
            text(
                """
                SELECT source_file_id FROM container_files
                WHERE container_id = :cid ORDER BY ordinal LIMIT 1
                """
            ),
            {"cid": cid},
        ).scalar()
        _reset_container(
            conn,
            cid,
            status=ContainerStatus.pending.value,
            failure=None,
            source_file_id=int(first) if first is not None else None,
            fmt=None,
        )
        seeded += 1

    orphans = [rec for rec in loose if path_to_id[rec.path] not in sf_to_cid]
    for batch in iter_loose_batches(orphans):
        file_ids = [path_to_id[rec.path] for rec in batch.files]
        _insert_container(
            conn,
            source_file_id=file_ids[0],
            kind=ContainerKind.loose_batch.value,
            fmt=None,
            depth=LOOSE_BATCH_DEPTH,
            status=ContainerStatus.pending.value,
            failure=None,
            file_ids=file_ids,
        )
        seeded += 1
    return seeded


def persist_walk(
    files: Sequence[WalkFile],
    groups: Sequence[ArchiveGroup],
    counts: WalkCounts,
    *,
    engine: Engine,
    worker_id: str | None,
) -> int:
    """Write source_files + seed containers. Returns sweep_runs.id."""
    with engine.begin() as conn:
        sweep_id = conn.execute(
            text(
                """
                INSERT INTO sweep_runs (kind, worker_id)
                VALUES (CAST(:kind AS sweep_kind), :worker)
                RETURNING id
                """
            ),
            {"kind": SweepKind.walk.value, "worker": worker_id},
        ).scalar_one()

        conn.execute(
            text(
                """
                CREATE TEMP TABLE walk_stage (
                    path text PRIMARY KEY,
                    size bigint NOT NULL,
                    mtime timestamptz NOT NULL,
                    kind text NOT NULL,
                    format text,
                    volume_set text
                ) ON COMMIT DROP
                """
            )
        )
        stage_rows = [
            {
                "path": rec.path,
                "size": rec.size,
                "mtime": datetime_from_mtime_ns(rec.mtime_ns),
                "kind": rec.kind.value,
                "format": rec.format,
                "volume_set": rec.volume_set,
            }
            for rec in files
        ]
        _exec_chunked(
            conn,
            text(
                """
                INSERT INTO walk_stage (path, size, mtime, kind, format, volume_set)
                VALUES (:path, :size, :mtime, :kind, :format, :volume_set)
                """
            ),
            stage_rows,
        )

        vanished = conn.execute(
            text(
                """
                SELECT count(*) FROM source_files s
                WHERE s.present
                  AND NOT EXISTS (SELECT 1 FROM walk_stage w WHERE w.path = s.path)
                """
            )
        ).scalar_one()
        conn.execute(
            text(
                """
                UPDATE source_files s SET present = false
                WHERE s.present
                  AND NOT EXISTS (SELECT 1 FROM walk_stage w WHERE w.path = s.path)
                """
            )
        )

        unchanged = conn.execute(
            text(
                """
                SELECT count(*) FROM source_files s
                JOIN walk_stage w ON w.path = s.path
                WHERE s.size = w.size AND s.mtime = w.mtime
                """
            )
        ).scalar_one()
        conn.execute(
            text(
                """
                UPDATE source_files s
                SET last_seen_sweep = :sid, present = true
                FROM walk_stage w
                WHERE s.path = w.path AND s.size = w.size AND s.mtime = w.mtime
                """
            ),
            {"sid": sweep_id},
        )

        changed_rows = conn.execute(
            text(
                """
                SELECT s.path FROM source_files s
                JOIN walk_stage w ON w.path = s.path
                WHERE s.size IS DISTINCT FROM w.size
                   OR s.mtime IS DISTINCT FROM w.mtime
                """
            )
        ).all()
        changed_paths = {row[0] for row in changed_rows}
        conn.execute(
            text(
                """
                UPDATE source_files s
                SET size = w.size,
                    mtime = w.mtime,
                    kind = CAST(w.kind AS source_file_kind),
                    format = w.format,
                    volume_set = w.volume_set,
                    last_seen_sweep = :sid,
                    present = true
                FROM walk_stage w
                WHERE s.path = w.path
                  AND (s.size IS DISTINCT FROM w.size OR s.mtime IS DISTINCT FROM w.mtime)
                """
            ),
            {"sid": sweep_id},
        )

        new_rows = conn.execute(
            text(
                """
                SELECT w.path FROM walk_stage w
                WHERE NOT EXISTS (SELECT 1 FROM source_files s WHERE s.path = w.path)
                """
            )
        ).all()
        new_paths = {row[0] for row in new_rows}
        conn.execute(
            text(
                """
                INSERT INTO source_files (
                    path, size, mtime, kind, format, volume_set,
                    first_seen_sweep, last_seen_sweep, present
                )
                SELECT w.path, w.size, w.mtime, CAST(w.kind AS source_file_kind),
                       w.format, w.volume_set, :sid, :sid, true
                FROM walk_stage w
                WHERE NOT EXISTS (SELECT 1 FROM source_files s WHERE s.path = w.path)
                """
            ),
            {"sid": sweep_id},
        )

        conn.execute(
            text(
                """
                DELETE FROM container_files cf
                USING source_files sf, containers c
                WHERE cf.source_file_id = sf.id
                  AND cf.container_id = c.id
                  AND (
                    (sf.kind = 'archive' AND c.kind = 'loose_batch')
                    OR (sf.kind = 'loose' AND c.kind = 'archive')
                  )
                """
            )
        )

        id_rows = conn.execute(
            text(
                """
                SELECT s.path, s.id FROM source_files s
                JOIN walk_stage w ON w.path = s.path
                """
            )
        ).all()
        path_to_id = {path: int(sid) for path, sid in id_rows}

        seeded = _sync_archive_groups(conn, groups, path_to_id, changed_paths, new_paths)
        seeded += _sync_loose_batches(conn, files, path_to_id, changed_paths)

        counts.new = int(len(new_paths))
        counts.changed = int(len(changed_paths))
        counts.unchanged = int(unchanged)
        counts.vanished = int(vanished)
        counts.containers_seeded = int(seeded)

        notes = json.dumps(
            {
                "dirs": counts.dirs,
                "archives": counts.archives,
                "loose": counts.loose,
                "symlinks": counts.symlinks,
                "skipped_dirs": counts.skipped_dirs,
                "errors": counts.errors,
            },
            separators=(",", ":"),
        )
        conn.execute(
            text(
                """
                UPDATE sweep_runs SET
                    finished_at = now(),
                    files_seen = :seen,
                    files_new = :new,
                    files_unchanged = :unchanged,
                    files_changed = :changed,
                    files_vanished = :vanished,
                    containers_seeded = :seeded,
                    bytes_read = :bytes,
                    notes = :notes
                WHERE id = :sid
                """
            ),
            {
                "sid": sweep_id,
                "seen": counts.files,
                "new": counts.new,
                "unchanged": counts.unchanged,
                "changed": counts.changed,
                "vanished": counts.vanished,
                "seeded": counts.containers_seeded,
                "bytes": counts.bytes,
                "notes": notes,
            },
        )
        return int(sweep_id)


def run(
    *,
    source_root: str | os.PathLike[str] | None = None,
    dry_run: bool = False,
    threads: int = DEFAULT_THREADS,
    db_url: str | None = None,
    skip_dirs: frozenset[str] | None = None,
) -> WalkResult:
    """Walk FORGE_SOURCE_ROOT and seed containers (or count only when dry_run).

    Programmatic entry for SPEC-007. Does not hash loose files.
    """
    cfg = ForgeConfig.from_env()
    root = os.path.abspath(os.fspath(source_root or cfg.require_source_root()))
    skip = skip_dirs if skip_dirs is not None else cfg.skip_dirs
    files, counts = walk_tree(root, threads=threads, skip_dirs=skip)
    files, groups = group_archive_sets(files)
    if dry_run:
        counts.containers_seeded = len(groups) + len(iter_loose_batches(files))
        return WalkResult(sweep_id=None, counts=counts, dry_run=True)

    url = normalize_db_url(db_url) if db_url else cfg.require_db_url()
    from forge.db.session import get_engine

    engine = get_engine(url)
    sweep_id = persist_walk(files, groups, counts, engine=engine, worker_id=cfg.worker_id)
    return WalkResult(sweep_id=sweep_id, counts=counts, dry_run=False)


def run_from_path(root: str | Path, **kwargs) -> WalkResult:
    """Alias kept for SPEC-007: ``run(source_root=root, ...)``."""
    return run(source_root=root, **kwargs)
