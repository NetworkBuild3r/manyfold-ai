"""Extract exactly the planned members of one source container into the blob store.

One sequential pass per source container (ADR D-2), using the engine's own readers and name
rules so member chains are computed exactly as the catalog recorded them (normalized names,
``//dupN`` for repeats, refused members skipped):

* libarchive streaming read (multi-volume via ``archive_read_open_filenames``);
* single-file gzip/bzip2/xz via the stream modules;
* ``7zz`` fallback (only the needed member names, extracted into a private scratch dir) when
  libarchive fails on zip/rar/7z — the same condition the engine uses.

A member that is wanted is streamed into ``.forge-blobs/<aa>/<bb>/tmp-*`` and published only
after its sha256 matched (:meth:`BlobStore.commit`). A member whose chain is a prefix of a wanted
chain (a nested archive) is spooled to local scratch, checked against the nested container's
catalog sha, and recursed into. Every other member is skipped — never written anywhere.
"""

from __future__ import annotations

import ctypes
import lzma
import os
import signal
import subprocess
import time
import zlib
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from forge.engine.archive import FALLBACK_FORMATS, READ_BLOCK, STREAM_FORMATS, map_error
from forge.engine.caps import Budget, Caps, FatalFailure, LocalFailure
from forge.engine.fallback import (
    _Concat,
    _open_stream,
    _safe_basename,
    _seven_zip_reason,
    entry_type,
    parse_slt,
    peek_stream,
    stream_member_name,
)
from forge.engine.kinds import MAGIC_BYTES, magic_format
from forge.engine.refuse import AE_IFDIR, check_filetype, check_name, decode_name

from .guard import WriteGuard
from .store import BlobStore, ShaMismatch, StoreCorrupt, TempWriter

Chain = tuple[str, ...]
_DUMMY_PASSWORD = "-pforge-no-password"


@dataclass(frozen=True)
class Want:
    sha: str
    size: int


@dataclass(frozen=True)
class Outcome:
    state: str  # done | failed
    method: str | None = None  # extracted | existing
    error: str | None = None


def _sniff(path: Path) -> bytes:
    fd = WriteGuard.open_read(path)
    try:
        return os.read(fd, MAGIC_BYTES)
    finally:
        os.close(fd)


def _file_chunks(path: str) -> Iterator[bytes]:
    fd = WriteGuard.open_read(path)
    try:
        while True:
            data = os.read(fd, READ_BLOCK)
            if not data:
                return
            yield data
    finally:
        os.close(fd)


class Extractor:
    def __init__(
        self,
        guard: WriteGuard,
        store: BlobStore,
        *,
        scratch: Path,
        caps: Caps,
        tag: str,
        sevenzip: str | None,
        throttle: Callable[[int], None] | None = None,
    ) -> None:
        self.guard, self.store = guard, store
        self.scratch, self.caps, self.tag, self.sevenzip = scratch, caps, tag, sevenzip
        self.throttle = throttle or (lambda _n: None)
        self.pending: dict[Chain, Want] = {}
        self.remaining: Counter = Counter()
        self.prefixes: set[Chain] = set()
        self.outcomes: dict[str, Outcome] = {}
        self.nested_shas: dict[Chain, str] = {}
        self.rundir: Path | None = None
        self.budget: Budget | None = None
        self.bytes_read = 0

    # ------------------------------------------------------------------------------- driver
    def run(
        self,
        volumes: list[Path],
        wants: dict[Chain, Want],
        nested_shas: dict[Chain, str] | None = None,
    ) -> dict[str, Outcome]:
        """Extract ``wants`` (member chain -> blob) from the container made of ``volumes``.
        Returns ``sha -> Outcome`` for every wanted blob."""
        self.pending = dict(wants)
        self.remaining = Counter()
        for chain in wants:
            for i in range(len(chain)):
                self.remaining[chain[:i]] += 1
        self.prefixes = {c[:i] for c in wants for i in range(1, len(c))}
        self.nested_shas = dict(nested_shas or {})
        self.outcomes = {}
        compressed = sum(os.stat(p).st_size for p in volumes)
        self.budget = Budget(self.caps, compressed)
        self.rundir = Path(self.guard.mkdtemp(self.scratch, "mat-run-", area="scratch"))
        try:
            self._container(list(volumes), (), 1, volumes[0].name)
        except FatalFailure as f:
            self._fail_under((), f.reason, f.detail)
        finally:
            self.guard.rmtree_scratch(self.rundir)
            self.rundir = None
        self._fail_under((), "not_found", "member not found in a full pass")
        return self.outcomes

    # ----------------------------------------------------------------------------- bookkeeping
    def _resolve(self, chain: Chain, outcome: Outcome) -> None:
        want = self.pending.pop(chain, None)
        if want is None:
            return
        for i in range(len(chain)):
            self.remaining[chain[:i]] -= 1
        prev = self.outcomes.get(want.sha)
        if prev is None or (prev.state != "done" and outcome.state == "done"):
            self.outcomes[want.sha] = outcome

    def _remaining_under(self, prefix: Chain) -> bool:
        return self.remaining[prefix] > 0

    def _fail_under(self, prefix: Chain, reason: str, detail: str | None = None) -> None:
        n = len(prefix)
        for chain in [c for c in self.pending if c[:n] == prefix]:
            msg = reason if not detail else f"{reason}: {detail}"[:500]
            self._resolve(chain, Outcome("failed", error=msg))

    # ------------------------------------------------------------------------------ containers
    def _container(self, paths: list[Path], prefix: Chain, depth: int, name_hint: str) -> None:
        if not self._remaining_under(prefix):
            return
        try:
            fmt = magic_format(_sniff(paths[0]))
        except OSError as x:
            self._fail_under(prefix, "reader_error", f"open: {x}")
            return
        if fmt in STREAM_FORMATS:
            inner = peek_stream(paths, fmt, MAGIC_BYTES)
            if inner is None or magic_format(inner) is None:
                try:
                    self._stream(paths, prefix, depth, fmt, name_hint)
                except LocalFailure as f:
                    self._fail_under(prefix, f.reason, f.detail)
                return
        try:
            self._libarchive(paths, prefix, depth)
        except LocalFailure as first:
            if (
                self._remaining_under(prefix)
                and first.reason in ("reader_error", "unsupported_format", "missing_volume")
                and fmt in FALLBACK_FORMATS
                and self.sevenzip
            ):
                try:
                    self._sevenzip(paths, prefix, depth, name_hint)
                except LocalFailure as second:
                    self._fail_under(
                        prefix, second.reason, f"libarchive: {first.detail}; 7zz: {second.detail}"
                    )
            else:
                self._fail_under(prefix, first.reason, first.detail)

    def _libarchive(self, paths: list[Path], prefix: Chain, depth: int) -> None:
        from forge.engine._libarchive import LibarchiveError, Reader

        buf = ctypes.create_string_buffer(READ_BLOCK)
        mv = memoryview(buf).cast("B")
        seen: Counter = Counter()
        try:
            with Reader(paths, READ_BLOCK) as r:
                while self._remaining_under(prefix):
                    self.budget.check_time()
                    e = r.next()
                    if e is None:
                        return
                    name = decode_name(e.raw_name)
                    if e.filetype == AE_IFDIR and not (e.symlink or e.hardlink):
                        continue
                    norm, why = check_name(name)
                    if why is None:
                        why = check_filetype(e.filetype, e.hardlink, e.symlink)
                    if why is not None:
                        continue  # refused by the catalog too: never extracted
                    k = seen[norm]
                    seen[norm] += 1
                    chain = prefix + ((norm if k == 0 else f"{norm}//dup{k}"),)
                    if chain not in self.pending and chain not in self.prefixes:
                        continue  # skipped: libarchive discards its data on next()
                    if e.encrypted:
                        self._fail_under(chain, "encrypted", name)
                        continue
                    if e.size is not None:
                        self.budget.check_member(e.size, None)

                    def chunks(declared=e.size) -> Iterator[memoryview]:
                        if declared == 0:
                            return
                        while True:
                            n = r.read_into(buf, READ_BLOCK)
                            if n == 0:
                                return
                            yield mv[:n]

                    self._take(chain, depth, chunks(), e.size)
        except LibarchiveError as x:
            raise LocalFailure(map_error(str(x)), str(x)[:300]) from None

    def _stream(self, paths: list[Path], prefix: Chain, depth: int, fmt: str, hint: str) -> None:
        norm, why = check_name(stream_member_name(hint, fmt))
        if why is not None:  # pragma: no cover - stream_member_name sanitizes
            norm = "data"
        chain = prefix + (norm,)
        if chain not in self.pending and chain not in self.prefixes:
            return
        raw = _Concat(paths)
        try:
            with _open_stream(fmt, raw) as z:
                self._take(chain, depth, iter(lambda: z.read(READ_BLOCK), b""), None)
        except (EOFError, OSError, lzma.LZMAError, zlib.error, ValueError) as x:
            raise LocalFailure("reader_error", f"{fmt}: {type(x).__name__}: {x}"[:300]) from None
        finally:
            raw.close()

    # ---------------------------------------------------------------------------------- member
    def _take(self, chain: Chain, depth: int, chunks, declared: int | None) -> None:
        """Stream one member: into a blob temp file if wanted, onto a scratch spool if it is a
        nested archive on the way to a wanted member, or both."""
        want = self.pending.get(chain)
        if want is not None and self.store.has(want.sha, want.size):
            self._resolve(chain, Outcome("done", "existing"))
            want = None
        opener = chain in self.prefixes and self._remaining_under(chain)
        if want is None and not opener:
            return
        writer = self.store.begin(want.sha, self.tag) if want is not None else None
        spool: TempWriter | None = None
        spooled = 0
        if opener:
            spool = TempWriter(
                self.guard,
                self.guard.new_temp_name(self.rundir, "spool-", "scratch"),
                "scratch",
                durable=False,
            )
        size = 0
        try:
            for data in chunks:
                n = len(data)
                size += n
                self.budget.check_time()
                self.budget.check_member(size, None)
                self.throttle(n)
                if writer is not None:
                    writer.write(data)
                if spool is not None:
                    if not self.budget.reserve_spool(n):
                        raise LocalFailure("spool_exceeded", "/".join(chain))
                    spooled += n
                    spool.write(data)
            if declared is not None and declared != size:
                raise LocalFailure("reader_error", f"{chain[-1]}: read {size} of {declared} bytes")
        except BaseException:
            if writer is not None:
                writer.abort()
            if spool is not None:
                spool.abort()
                self.budget.release_spool(spooled)
            raise
        self.bytes_read += size
        if writer is not None:
            try:
                method = self.store.commit(writer, want.sha, want.size)
                self._resolve(chain, Outcome("done", method))
            except ShaMismatch as m:
                self._resolve(chain, Outcome("failed", error=f"sha_mismatch: got {m.got}"))
            except StoreCorrupt as x:
                self._resolve(chain, Outcome("failed", error=f"store_corrupt: {x}"[:500]))
        if spool is None:
            return
        try:
            spool.close()
            nested_sha = self.nested_shas.get(chain)
            if nested_sha and spool.sha.hexdigest() != nested_sha:
                self._fail_under(chain, "sha_mismatch", "nested archive differs from the catalog")
            elif depth + 1 > self.caps.depth:
                self._fail_under(chain, "depth_exceeded", f"cap {self.caps.depth}")
            else:
                hint = chain[-1].split("//", 1)[0].rsplit("/", 1)[-1]
                self._container([Path(spool.path)], chain, depth + 1, hint)
        finally:
            spool.abort()
            self.budget.release_spool(spooled)

    # ------------------------------------------------------------------------------------- 7zz
    def _run(self, argv: list[str]) -> subprocess.CompletedProcess:
        env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"}
        env["HOME"] = str(self.rundir)
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.rundir,
            env=env,
            start_new_session=True,
        )
        try:
            out, err = proc.communicate(timeout=max(1.0, self.budget.remaining_seconds()))
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise FatalFailure("timeout", "7zz exceeded the wall-time cap") from None
        except BaseException:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise
        return subprocess.CompletedProcess(argv, proc.returncode, out, err)

    def _sevenzip(self, paths: list[Path], prefix: Chain, depth: int, name_hint: str) -> None:
        linkdir = Path(self.guard.mkdtemp(self.rundir, "vol-", area="scratch"))
        outdir = Path(self.guard.mkdtemp(self.rundir, "x-", area="scratch"))
        reserved = 0
        try:
            names = []
            for i, p in enumerate(paths):
                hint = name_hint if len(paths) == 1 else p.name
                link = linkdir / _safe_basename(hint, f"volume{i}")
                names.append(self.guard.symlink_in_scratch(os.path.abspath(p), link))
            common = ["-sccUTF-8", "-scsUTF-8", _DUMMY_PASSWORD, "-bd"]
            listed = self._run([self.sevenzip, "l", "-slt", *common, "--", names[0]])
            err = listed.stderr.decode("utf-8", "backslashreplace")
            if listed.returncode != 0:
                raise LocalFailure(
                    _seven_zip_reason(listed.returncode, err),
                    f"7zz l rc={listed.returncode}: {err.strip()[:200]}",
                )
            entries = parse_slt(listed.stdout.decode("utf-8", "backslashreplace"))
            seen: Counter = Counter()
            selected: list[tuple[dict, str, Chain]] = []
            for e in entries:
                kind = entry_type(e)
                if kind == "dir":
                    continue
                norm, why = check_name(e["Path"])
                if why is None and kind != "file":
                    why = kind
                if why is not None:
                    continue
                k = seen[norm]
                seen[norm] += 1
                chain = prefix + ((norm if k == 0 else f"{norm}//dup{k}"),)
                if chain not in self.pending and chain not in self.prefixes:
                    continue
                if e.get("Encrypted") == "+":
                    self._fail_under(chain, "encrypted", e["Path"])
                    continue
                selected.append((e, norm, chain))
            if not selected:
                return
            total = sum(int(e.get("Size") or 0) for e, _, _ in selected)
            if not self.budget.reserve_spool(total):
                raise LocalFailure("spool_exceeded", f"7zz extraction needs {total} bytes")
            reserved = total
            listfile = TempWriter(self.guard, str(linkdir / ".include"), "scratch", durable=False)
            listfile.write("".join(e["Path"] + "\n" for e, _, _ in selected).encode("utf-8"))
            listfile.close()
            x = self._run(
                [self.sevenzip, "x", "-y", *common, "-mmt=1", "-spd", f"-i@{listfile.path}"]
                + [f"-o{outdir}", "--", names[0]]
            )
            x_err = x.stderr.decode("utf-8", "backslashreplace")
            for e, norm, chain in selected:
                path = outdir / norm
                try:
                    real = path.resolve(strict=True)
                except OSError:
                    continue  # left pending -> fails below with the 7zz reason
                if outdir.resolve() not in real.parents or not real.is_file():
                    continue
                listed_size = e.get("Size")
                declared = int(listed_size) if listed_size not in (None, "") else None
                try:
                    self._take(chain, depth, _file_chunks(str(real)), declared)
                except LocalFailure as f:
                    self._fail_under(chain, f.reason, f.detail)
                finally:
                    try:
                        self.guard.unlink(real, "scratch")
                    except FileNotFoundError:
                        pass
            if self._remaining_under(prefix):
                self._fail_under(
                    prefix,
                    _seven_zip_reason(x.returncode, x_err),
                    f"7zz x rc={x.returncode}: {x_err.strip()[:200]}",
                )
        finally:
            self.guard.rmtree_scratch(outdir)
            self.guard.rmtree_scratch(linkdir)
            self.budget.release_spool(reserved)


class TokenBucket:
    """Simple per-process IO budget (bytes/s). ``rate <= 0`` disables throttling."""

    def __init__(self, rate_bytes_per_s: float) -> None:
        self.rate = float(rate_bytes_per_s)
        self.tokens = self.rate
        self.last = time.monotonic()

    def __call__(self, n: int) -> None:
        if self.rate <= 0:
            return
        now = time.monotonic()
        self.tokens = min(self.rate, self.tokens + (now - self.last) * self.rate)
        self.last = now
        self.tokens -= n
        if self.tokens < 0:
            time.sleep(-self.tokens / self.rate)
