"""Content-addressed blob store ``<v2>/.forge-blobs/<aa>/<bb>/<sha256>`` (ADR D-6 / D-6a).

A blob is published only after its bytes were hashed and matched the catalog sha256
(GR-004 for writes): extraction goes to ``<aa>/<bb>/tmp-<unit>-<rand>`` (created ``O_EXCL``),
is fsync'ed, verified, then hardlinked to its final name (``link`` never overwrites) and the temp
name removed. A loose source file is published by hardlinking the source file itself (no copy;
the source inode is not modified). Pack files are hardlinks of the store entry; if the kernel
refuses a hardlink (EXDEV, EPERM, ENOTSUP, EMLINK) a verified copy is written instead.

All filesystem writes go through :class:`forge.materialize.guard.WriteGuard`.
"""

from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .guard import WriteGuard

BLOB_DIR = ".forge-blobs"
_SHA = re.compile(r"^[0-9a-f]{64}$")
COPY_FALLBACK_ERRNOS = frozenset(
    {errno.EXDEV, errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EMLINK, errno.EACCES}
)
CHUNK = 1 << 20


class ShaMismatch(Exception):
    def __init__(self, want: str, got: str, size: int) -> None:
        super().__init__(f"sha256 mismatch: want {want} got {got} ({size} bytes)")
        self.want, self.got, self.size = want, got, size


class CopyDisabled(Exception):
    """A hardlink failed and copy fallback is disabled."""


class StoreCorrupt(Exception):
    """A store entry exists under a sha name but has the wrong size / type."""


Throttle = Callable[[int], None]


def _no_throttle(_n: int) -> None:
    return None


def hash_path(path: str | os.PathLike, throttle: Throttle = _no_throttle) -> tuple[str, int]:
    """sha256 + size of a file, read-only (``O_RDONLY | O_NOFOLLOW``)."""
    h = hashlib.sha256()
    size = 0
    fd = WriteGuard.open_read(path)
    try:
        while True:
            data = os.read(fd, CHUNK)
            if not data:
                break
            throttle(len(data))
            h.update(data)
            size += len(data)
    finally:
        os.close(fd)
    return h.hexdigest(), size


@dataclass
class Counters:
    linked: int = 0
    copied: int = 0
    existing: int = 0
    replaced: int = 0
    extracted: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


class TempWriter:
    """A new temp file (``O_EXCL``) that hashes what is written. :meth:`commit` verifies and
    publishes it; :meth:`abort` removes it. Nothing is visible under the final name before the
    hash matched."""

    def __init__(
        self, guard: WriteGuard, tmp_path: str, area: str = "v2", *, durable: bool = True
    ) -> None:
        self.guard, self.area, self.durable = guard, area, durable
        self.path = tmp_path
        self.fd: int | None = guard.open_new(tmp_path, area)
        self.sha = hashlib.sha256()
        self.size = 0

    def write(self, data) -> None:
        view = memoryview(data)
        self.sha.update(view)
        self.size += len(view)
        while view:
            n = os.write(self.fd, view)
            view = view[n:]

    def close(self) -> None:
        if self.fd is not None:
            try:
                if self.durable:
                    os.fsync(self.fd)
            finally:
                os.close(self.fd)
                self.fd = None

    def verify(self, want_sha: str, want_size: int) -> None:
        self.close()
        got = self.sha.hexdigest()
        if got != want_sha or self.size != want_size:
            raise ShaMismatch(want_sha, got, self.size)

    def abort(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        try:
            self.guard.unlink(self.path, self.area)
        except FileNotFoundError:
            pass


class BlobStore:
    def __init__(
        self,
        guard: WriteGuard,
        *,
        allow_copy: bool = True,
        throttle: Throttle = _no_throttle,
    ) -> None:
        self.guard = guard
        self.root = Path(guard.v2_root) / BLOB_DIR
        self.allow_copy = allow_copy
        self.throttle = throttle
        self.counters = Counters()

    # --------------------------------------------------------------------------- naming
    def path(self, sha: str) -> Path:
        if not _SHA.match(sha):
            raise ValueError(f"not a sha256: {sha!r}")
        return self.root / sha[:2] / sha[2:4] / sha

    def temp_prefix(self, tag: str) -> str:
        return f"tmp-{tag}-"

    def has(self, sha: str, size: int) -> bool:
        """The store already holds ``sha`` as a regular file of the right size."""
        try:
            st = os.lstat(self.path(sha))
        except FileNotFoundError:
            return False
        return stat.S_ISREG(st.st_mode) and st.st_size == size

    def clean_temps(self, shas: list[str], tag: str) -> int:
        """Remove ``tmp-<tag>-*`` left by a killed attempt of the same unit (v2 only)."""
        removed = 0
        prefix = self.temp_prefix(tag)
        for d in sorted({self.path(s).parent for s in shas}):
            try:
                names = os.listdir(d)
            except FileNotFoundError:
                continue
            for name in names:
                if name.startswith(prefix):
                    try:
                        self.guard.unlink(d / name)
                        removed += 1
                    except FileNotFoundError:
                        pass
        return removed

    # -------------------------------------------------------------------------- writers
    def begin(self, sha: str, tag: str) -> TempWriter:
        final = self.path(sha)
        self.guard.mkdirs(final.parent)
        return TempWriter(self.guard, self.guard.new_temp_name(final.parent, self.temp_prefix(tag)))

    def commit(self, w: TempWriter, sha: str, size: int) -> str:
        """Verify ``w`` against (sha, size) and publish it. Returns ``extracted``/``existing``.
        On mismatch the temp file is removed and :class:`ShaMismatch` raised."""
        try:
            w.verify(sha, size)
        except BaseException:
            w.abort()
            raise
        final = self.path(sha)
        try:
            self._publish(w.path, final)
            method = "extracted"
            self.counters.extracted += 1
        except FileExistsError:
            if not self.has(sha, size):
                raise StoreCorrupt(f"{final} exists but is not a {size}-byte file") from None
            method = "existing"
            self.counters.existing += 1
        finally:
            try:
                self.guard.unlink(w.path)
            except FileNotFoundError:
                pass
        return method

    def _publish(self, tmp: str, final: Path) -> None:
        try:
            self.guard.link(tmp, final)
        except OSError as x:
            if x.errno == errno.EEXIST:
                raise FileExistsError(str(final)) from None
            if x.errno not in COPY_FALLBACK_ERRNOS:
                raise
            # No hardlinks inside v2 at all: move the verified temp into place (never over an
            # existing entry — same content anyway).
            if os.path.lexists(final):
                raise FileExistsError(str(final)) from None
            self.guard.rename(tmp, final)

    def copy_into(self, src: str | os.PathLike, sha: str, size: int, tag: str) -> str:
        """Verified copy of ``src`` (read-only) into the store."""
        w = self.begin(sha, tag)
        try:
            fd = WriteGuard.open_read(src)
            try:
                while True:
                    data = os.read(fd, CHUNK)
                    if not data:
                        break
                    self.throttle(len(data))
                    w.write(data)
            finally:
                os.close(fd)
        except BaseException:
            w.abort()
            raise
        return self.commit(w, sha, size)

    def link_from_source(self, src: str | os.PathLike, sha: str, size: int, tag: str) -> str:
        """Publish a loose source file: hardlink it into the store (``linked``), keep an existing
        entry (``existing``), or — when the kernel refuses the link — a verified copy
        (``copied``)."""
        final = self.path(sha)
        self.guard.mkdirs(final.parent)
        try:
            self.guard.link(src, final)
            self.counters.linked += 1
            return "linked"
        except FileExistsError:
            if not self.has(sha, size):
                raise StoreCorrupt(f"{final} exists but is not a {size}-byte file") from None
            self.counters.existing += 1
            return "existing"
        except OSError as x:
            if x.errno not in COPY_FALLBACK_ERRNOS:
                raise
            if not self.allow_copy:
                raise CopyDisabled(f"link {src} -> store refused ({errno.errorcode[x.errno]})")
        method = self.copy_into(src, sha, size, tag)
        if method == "extracted":
            self.counters.extracted -= 1
            self.counters.copied += 1
            return "copied"
        return method

    # ------------------------------------------------------------------------ pack files
    def place(self, sha: str, size: int, target: Path, *, verify_existing: bool = True) -> str:
        """Make ``target`` (a pack file) hold blob ``sha``: ``skipped`` if it already is the store
        inode (or an identical copy), ``linked``/``copied`` when created, ``replaced`` when a wrong
        file was atomically swapped (temp name + rename; the old v2 name is dropped, no bytes of
        any existing inode are modified)."""
        src = self.path(sha)
        bst = os.stat(src, follow_symlinks=False)
        try:
            tst = os.lstat(target)
        except FileNotFoundError:
            tst = None
        if tst is not None:
            if stat.S_ISDIR(tst.st_mode):
                raise IsADirectoryError(f"{target} is a directory; expected blob {sha}")
            if stat.S_ISREG(tst.st_mode) and (tst.st_ino, tst.st_dev) == (bst.st_ino, bst.st_dev):
                self.counters.existing += 1
                return "skipped"
            if stat.S_ISREG(tst.st_mode) and tst.st_size == size and verify_existing:
                got, _ = hash_path(target, self.throttle)
                if got == sha:
                    self.counters.existing += 1
                    return "skipped"
            tmp = self.guard.new_temp_name(target.parent, ".forge-tmp-")
            how = self._link_or_copy(src, Path(tmp), sha, size)
            self.guard.rename(tmp, target)
            self.counters.replaced += 1
            return "replaced" if how == "linked" else "replaced_copy"
        self.guard.mkdirs(target.parent)
        return self._link_or_copy(src, target, sha, size)

    def _link_or_copy(self, src: Path, dst: Path, sha: str, size: int) -> str:
        try:
            self.guard.link(src, dst)
            self.counters.linked += 1
            return "linked"
        except OSError as x:
            if x.errno not in COPY_FALLBACK_ERRNOS:
                raise
            if not self.allow_copy:
                raise CopyDisabled(f"link {src} -> {dst} refused ({errno.errorcode[x.errno]})")
        tmp = self.guard.new_temp_name(dst.parent, ".forge-tmp-")
        w = TempWriter(self.guard, tmp)
        try:
            fd = WriteGuard.open_read(src)
            try:
                while True:
                    data = os.read(fd, CHUNK)
                    if not data:
                        break
                    self.throttle(len(data))
                    w.write(data)
            finally:
                os.close(fd)
            w.verify(sha, size)
        except BaseException:
            w.abort()
            raise
        self.guard.rename(tmp, dst)
        self.counters.copied += 1
        return "copied"
