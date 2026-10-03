"""Recursive streaming archive traversal (libarchive first; 7zz / stream modules as fallback).

Runs inside the isolated reader process (see ``forge.engine._worker``) or in-process for tests.
Only ever writes to the per-run scratch directory: nested-archive spools and 7zz extraction dirs,
random names, deleted in ``finally``. Never executes archive contents.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import stat
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from forge.hashing import StlCounter, is_stl_name

from . import fallback
from .caps import Budget, Caps, EngineFailure, FatalFailure, LocalFailure
from .kinds import MAGIC_BYTES, classify, magic_format
from .refuse import AE_IFDIR, check_filetype, check_name, decode_name, display_name
from .types import Result, Sink

READ_BLOCK = 1 << 20
FALLBACK_FORMATS = frozenset({"zip", "rar4", "rar5", "7z"})
STREAM_FORMATS = frozenset({"gzip", "bzip2", "xz"})


@dataclass
class Ctx:
    sink: Sink
    caps: Caps
    budget: Budget
    scratch: Path
    sevenzip: str | None
    fatal: FatalFailure | None = None
    buf: ctypes.Array = field(
        default_factory=lambda: ctypes.create_string_buffer(READ_BLOCK)
    )


@dataclass
class ContainerState:
    prefix: tuple[str, ...]
    depth: int
    compressed: int
    name_hint: str
    members: int = 0
    bytes_out: int = (
        0  # uncompressed bytes read in this container (incl. refused/aborted data)
    )
    bytes_hashed: int = 0
    seen: Counter = field(
        default_factory=Counter
    )  # normalized name -> occurrences emitted
    handled: Counter = field(
        default_factory=Counter
    )  # keys finished by an earlier reader pass

    def chain_for(self, norm: str) -> tuple[str, ...]:
        k = self.seen[norm]
        self.seen[norm] += 1
        return self.prefix + ((norm if k == 0 else f"{norm}//dup{k}"),)


def map_error(message: str) -> str:
    m = message.lower()
    if "encrypt" in m or "passphrase" in m or "password" in m:
        return "encrypted"
    if "allocate" in m or "out of memory" in m:
        return "oom"
    if (
        "missing volume" in m
        or "volume" in m
        and ("missing" in m or "next" in m or "open" in m)
    ):
        return "missing_volume"
    if "unrecognized archive format" in m or "unsupported" in m or "not supported" in m:
        return "unsupported_format"
    return "reader_error"


class MemberWriter:
    """Hashes one member as it streams; spools it to scratch when it is a nested archive that
    will be opened. Nothing reaches the sink until :meth:`finish` (GR-004)."""

    def __init__(
        self, ctx: Ctx, st: ContainerState, norm: str, existing: Path | None = None
    ) -> None:
        self.ctx, self.st, self.norm = ctx, st, norm
        self.sha = hashlib.sha256()
        self.size = 0
        self.stl = StlCounter() if is_stl_name(norm) else None
        self.head = bytearray()
        self.kind: str | None = None
        self.existing = (
            existing  # already on scratch (7zz extraction): recurse on it directly
        )
        self.spool_path: Path | None = None
        self._spool = None
        self.spooled = 0
        self.spool_failed: str | None = None

    def _decide(self) -> None:
        self.kind = classify(self.norm, bytes(self.head))
        if self.kind != "archive" or self.existing is not None:
            return
        if self.st.depth + 1 > self.ctx.caps.depth:
            return
        fd, name = tempfile.mkstemp(prefix="spool-", dir=self.ctx.scratch)
        self.spool_path = Path(name)
        self._spool = os.fdopen(fd, "wb")
        self._spool_write(self.head)

    def _spool_write(self, data) -> None:
        if self._spool is None:
            return
        n = len(data)
        if not self.ctx.budget.reserve_spool(n):
            self.spool_failed = "spool_exceeded"
            self._drop_spool()
            return
        self.spooled += n
        self._spool.write(data)

    def _drop_spool(self) -> None:
        if self._spool is not None:
            self._spool.close()
            self._spool = None
        if self.spool_path is not None:
            self.spool_path.unlink(missing_ok=True)
            self.spool_path = None
        self.ctx.budget.release_spool(self.spooled)
        self.spooled = 0

    def feed(self, data: memoryview, compressed: int | None = None) -> None:
        ctx, st, n = self.ctx, self.st, len(data)
        ctx.budget.check_time()
        self.size += n
        st.bytes_out += n
        ctx.budget.add_tree_bytes(n)
        ctx.budget.check_member(self.size, compressed)
        ctx.budget.check_container(st.bytes_out, st.compressed)
        self.sha.update(data)
        if self.stl is not None:
            self.stl.feed(data)
        if self.kind is None:
            need = MAGIC_BYTES - len(self.head)
            self.head += data[:need]
            if len(self.head) >= MAGIC_BYTES:
                self._decide()  # spools the head
                if n > need:
                    self._spool_write(data[need:])
        else:
            self._spool_write(data)

    def abort(self) -> None:
        self._drop_spool()

    def finish(self) -> None:
        if self.kind is None:
            self._decide()
        if self._spool is not None:
            self._spool.close()
            self._spool = None
        ctx, st = self.ctx, self.st
        chain = st.chain_for(self.norm)
        sha = self.sha.hexdigest()
        tri = self.stl.result() if self.stl is not None else None
        ctx.sink.member(chain, sha, self.size, self.kind, tri, st.depth)
        st.members += 1
        st.bytes_hashed += self.size
        if self.kind != "archive":
            return
        ctx.sink.nested_archive(chain, sha, self.size)
        child_depth = st.depth + 1
        hint = self.norm.rsplit("/", 1)[-1]
        try:
            if child_depth > ctx.caps.depth:
                res = Result(
                    "failed",
                    "depth_exceeded",
                    0,
                    0,
                    child_depth,
                    detail=f"cap {ctx.caps.depth}",
                )
            elif self.spool_failed:
                res = Result("failed", self.spool_failed, 0, 0, child_depth)
            else:
                path = self.existing if self.existing is not None else self.spool_path
                res = open_container(ctx, [path], chain, child_depth, self.size, hint)
        finally:
            self._drop_spool()
        ctx.sink.nested_result(chain, res)
        if ctx.fatal is not None:
            raise ctx.fatal


def _drain(ctx: Ctx, st: ContainerState, reader) -> None:
    """Read and discard a refused member's data so caps still bound it."""
    buf = ctx.buf
    while True:
        ctx.budget.check_time()
        n = reader.read_into(buf, len(buf))
        if n == 0:
            return
        st.bytes_out += n
        ctx.budget.add_tree_bytes(n)


def refuse(ctx: Ctx, st: ContainerState, name: str, reason: str) -> None:
    key = "!" + display_name(name)
    st.seen[key] += 1
    ctx.sink.refused(st.prefix + (display_name(name),), reason)


def read_libarchive(ctx: Ctx, st: ContainerState, paths: list[Path]) -> str | None:
    from ._libarchive import LibarchiveError, Reader

    mv = memoryview(ctx.buf).cast("B")
    fmt_name = None
    try:
        with Reader(paths, READ_BLOCK) as r:
            while True:
                ctx.budget.check_time()
                e = r.next()
                if e is None:
                    return fmt_name
                fmt_name = fmt_name or r.format_name()
                name = decode_name(e.raw_name)
                if e.filetype == AE_IFDIR and not (e.symlink or e.hardlink):
                    continue
                norm, why = check_name(name)
                if why is None:
                    why = check_filetype(e.filetype, e.hardlink, e.symlink)
                if why is not None:
                    refuse(ctx, st, name, why)
                    _drain(ctx, st, r)
                    continue
                if e.encrypted:
                    raise LocalFailure("encrypted", name)
                if e.size is not None:
                    ctx.budget.check_member(e.size, None)
                w = MemberWriter(ctx, st, norm)
                c0 = r.compressed_bytes()
                try:
                    # libarchive 3.8 RAR5: read_data on a zero-length member of a solid stream
                    # fails ("Unsupported block header size"); a declared-empty member has no data.
                    while e.size != 0:
                        n = r.read_into(ctx.buf, READ_BLOCK)
                        if n == 0:
                            break
                        w.feed(mv[:n], r.compressed_bytes() - c0)
                    if e.size is not None and e.size != w.size:
                        raise LocalFailure(
                            "reader_error", f"{name}: read {w.size} of {e.size} bytes"
                        )
                except BaseException:
                    w.abort()
                    raise
                w.finish()
    except LibarchiveError as x:
        raise LocalFailure(map_error(str(x)), str(x)[:300]) from None


def _sniff(path: Path) -> bytes:
    with open(path, "rb") as f:
        return f.read(MAGIC_BYTES)


def open_container(
    ctx: Ctx,
    paths: list[Path],
    prefix: tuple[str, ...],
    depth: int,
    compressed: int,
    name_hint: str,
) -> Result:
    """Process one container (top-level source archive or a nested child). Never raises for a
    container failure: local failures become a failed Result; fatal ones also set ``ctx.fatal``."""
    st = ContainerState(prefix, depth, compressed, name_hint)
    ctx.budget.max_depth = max(ctx.budget.max_depth, depth)
    fmt = None
    reader = "libarchive"
    try:
        try:
            fmt = magic_format(_sniff(paths[0]))
        except OSError as x:
            raise LocalFailure("reader_error", f"open: {x}") from None
        # gzip/bzip2/xz: libarchive only when the decompressed head is itself an archive (tar.gz).
        # Otherwise libarchive can mistake plain content for a format (zeros = an empty tar,
        # text = mtree) and silently report zero members.
        if fmt in STREAM_FORMATS:
            inner = fallback.peek_stream(paths, fmt, MAGIC_BYTES)
            if inner is None or magic_format(inner) is None:
                reader = "stream"
                fallback.read_stream(ctx, st, paths, fmt)
                return _result(st, "done", None, fmt, reader)
        try:
            read_libarchive(ctx, st, paths)
            if fmt is None and not st.seen:
                # No archive magic and no entries: not something we recognise, never "done/0".
                raise LocalFailure(
                    "unsupported_format", "no entries and no archive signature"
                )
        except LocalFailure as first:
            if (
                first.reason in ("reader_error", "unsupported_format", "missing_volume")
                and fmt in FALLBACK_FORMATS
                and ctx.sevenzip
            ):
                reader = "7zz"
                st.handled, st.seen = Counter(st.seen), Counter()
                try:
                    fallback.read_7zz(ctx, st, paths)
                except LocalFailure as second:
                    raise LocalFailure(
                        second.reason
                        if second.reason != "reader_error"
                        else first.reason,
                        f"libarchive: {first.detail}; 7zz: {second.detail}",
                    ) from None
            else:
                raise
    except FatalFailure as f:
        ctx.fatal = ctx.fatal or f
        return _result(st, "failed", f, fmt, reader)
    except MemoryError:
        return _result(st, "failed", LocalFailure("oom", "MemoryError"), fmt, reader)
    except LocalFailure as f:
        return _result(st, "failed", f, fmt, reader)
    return _result(st, "done", None, fmt, reader)


def _result(
    st: ContainerState,
    status: str,
    f: EngineFailure | None,
    fmt: str | None,
    reader: str,
) -> Result:
    return Result(
        status,
        f.reason if f else None,
        st.members,
        st.bytes_hashed,
        st.depth,
        format=fmt,
        reader=reader,
        detail=(f.detail[:500] if f and f.detail else None),
    )


def run_archive(
    paths: list[Path],
    sink: Sink,
    caps: Caps,
    scratch: Path,
    sevenzip: str | None = None,
) -> Result:
    """Top-level archive container (depth 1). ``scratch`` is a private run directory."""
    compressed = 0
    for p in paths:
        try:
            st = os.stat(p)
        except FileNotFoundError:
            reason = "missing_volume" if len(paths) > 1 else "reader_error"
            return Result("failed", reason, 0, 0, 1, detail=f"missing: {p.name}")
        if not stat.S_ISREG(st.st_mode):
            return Result(
                "failed",
                "reader_error",
                0,
                0,
                1,
                detail=f"not a regular file: {p.name}",
            )
        compressed += st.st_size
    ctx = Ctx(sink, caps, Budget(caps, compressed), scratch, sevenzip)
    res = open_container(ctx, list(paths), (), 1, compressed, paths[0].name)
    return Result(
        res.status,
        res.reason,
        res.members,
        res.bytes_read,
        ctx.budget.max_depth,
        format=res.format,
        reader=res.reader,
        detail=res.detail,
    )
