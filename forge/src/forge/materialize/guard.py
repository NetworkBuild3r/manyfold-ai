"""Write guard — the ONLY module in ``forge.materialize`` that performs filesystem writes.

Hard line (INIT-032 GR-001, ADR D-6a): nothing under the SOURCE root is ever deleted, modified,
renamed or opened for write. The materializer may

* create files, directories, hardlinks, renames and unlinks **strictly under the v2 root**;
* use a local **scratch** directory (nested-archive spools, 7zz extraction) — never under the
  source root and never under the v2 root;
* create hardlinks whose *source* is a catalog file (``link(source_file, v2_path)`` adds a name in
  v2; the source inode's bytes and mtime are unchanged — only its link count and ctime move).

Every write primitive below resolves its target(s) with :meth:`WriteGuard.check` before the
syscall and passes the *resolved* path to the kernel, so a symlink inside v2 cannot redirect a
write into the source tree. New files are only ever created with ``O_CREAT | O_EXCL |
O_NOFOLLOW`` — an existing file (which in v2 may be a hardlink of a source inode) is never opened
for write, truncated, chmod'ed or utime'd. ``tests/materialize/test_fence.py`` fails the build if
any other materialize module calls a write primitive directly.

Residual risk (documented, accepted): check-then-act is not atomic against a concurrent attacker
swapping a v2 directory for a symlink between the check and the syscall. Only forge writes v2.
"""

from __future__ import annotations

import os
import secrets
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path

_NETWORK_FS = ("nfs", "nfs4", "cifs", "smb3", "smbfs", "fuse.sshfs", "9p", "ceph", "glusterfs")

# Flags the guard ever uses to create a file. Nothing here can open an existing inode.
NEW_FILE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_WRITE_BITS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


class GuardError(PermissionError):
    """A write was aimed outside the allowed roots (or at the source tree). Never caught."""


class StartupError(RuntimeError):
    """The mount layout is unsafe; the materializer refuses to start."""


def _is_under(path: str, root: str) -> bool:
    """``path`` is strictly inside ``root`` (both absolute, real)."""
    return path != root and path.startswith(root.rstrip("/") + "/")


def _is_under_or_equal(path: str, root: str) -> bool:
    return path == root or _is_under(path, root)


def mount_fstype(path: str) -> str:
    best, fstype = "", ""
    try:
        with open("/proc/self/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mnt = parts[1].replace("\\040", " ")
                if _is_under_or_equal(path, mnt) and len(mnt) > len(best):
                    best, fstype = mnt, parts[2]
    except OSError:
        return ""
    return fstype


@dataclass
class WriteGuard:
    """Resolves and checks every write target. Construct with :func:`open_guard`."""

    v2_root: str  # realpath
    source_root: str  # realpath
    scratch_root: str | None = None  # realpath
    writes: int = field(default=0, compare=False)

    # ------------------------------------------------------------------------------- checking
    def check(self, path: str | os.PathLike, area: str = "v2") -> str:
        """Return the resolved absolute path for a write in ``area`` (``v2`` | ``scratch``), or
        raise :class:`GuardError`. The parent is resolved with ``realpath`` (symlinks followed the
        way the kernel would); the last component is never followed by the write primitives."""
        p = os.fspath(path)
        if isinstance(p, bytes):
            raise GuardError("bytes paths are not accepted")
        if "\x00" in p:
            raise GuardError(f"NUL in path {p!r}")
        if not os.path.isabs(p):
            raise GuardError(f"relative path {p!r}")
        parent, name = os.path.split(p.rstrip("/") if p != "/" else p)
        if name in ("", ".", ".."):
            raise GuardError(f"unsafe final component in {p!r}")
        resolved = os.path.join(os.path.realpath(parent), name)
        if _is_under_or_equal(resolved, self.source_root):
            raise GuardError(f"write into the SOURCE tree refused: {p!r} -> {resolved!r}")
        root = self._root(area)
        if not _is_under(resolved, root):
            raise GuardError(f"write outside the {area} root refused: {p!r} -> {resolved!r}")
        return resolved

    def _root(self, area: str) -> str:
        if area == "v2":
            return self.v2_root
        if area == "scratch":
            if self.scratch_root is None:
                raise GuardError("no scratch root configured")
            return self.scratch_root
        raise GuardError(f"unknown area {area!r}")

    def check_link_source(self, path: str | os.PathLike) -> str:
        """A hardlink source must resolve (parent via realpath) under the source root or the v2
        root — a directory symlink planted in the source tree cannot pull an arbitrary file
        (e.g. under /etc) into v2. Returns the resolved path; the link never follows the final
        component."""
        p = os.fspath(path)
        if isinstance(p, bytes) or "\x00" in p or not os.path.isabs(p):
            raise GuardError(f"bad link source {p!r}")
        parent, name = os.path.split(p)
        if name in ("", ".", ".."):
            raise GuardError(f"unsafe link source {p!r}")
        resolved = os.path.join(os.path.realpath(parent), name)
        if not (_is_under(resolved, self.source_root) or _is_under(resolved, self.v2_root)):
            raise GuardError(f"link source outside source/v2 roots refused: {p!r} -> {resolved!r}")
        return resolved

    @staticmethod
    def assert_read_only_flags(flags: int) -> None:
        if flags & _WRITE_BITS:
            raise GuardError(f"open flags {flags:#o} are not read-only")

    # ------------------------------------------------------------------------- write primitives
    def mkdirs(self, path: str | os.PathLike, area: str = "v2") -> str:
        """``mkdir -p`` where every created component is checked. Returns the resolved path."""
        target = self.check(path, area)
        root = self._root(area)
        missing: list[str] = []
        cur = target
        while not os.path.isdir(cur):
            if os.path.lexists(cur):
                raise FileExistsError(f"{cur} exists and is not a directory")
            missing.append(cur)
            cur = os.path.dirname(cur)
            if not _is_under(cur, root) and cur != root:
                raise GuardError(f"mkdirs escaped the {area} root at {cur!r}")
        for d in reversed(missing):
            checked = self.check(d, area)
            try:
                os.mkdir(checked, 0o755)
                self.writes += 1
            except FileExistsError:
                if not os.path.isdir(checked):
                    raise
        return target

    def open_new(self, path: str | os.PathLike, area: str = "v2") -> int:
        """Create a NEW file (fails if anything exists at the path) and return a write fd."""
        target = self.check(path, area)
        fd = os.open(target, NEW_FILE_FLAGS, 0o644)
        self.writes += 1
        return fd

    def new_temp_name(self, directory: str | os.PathLike, prefix: str, area: str = "v2") -> str:
        name = f"{prefix}{secrets.token_hex(8)}"
        return self.check(os.path.join(os.fspath(directory), name), area)

    def mkdtemp(self, directory: str | os.PathLike, prefix: str, area: str = "scratch") -> str:
        for _ in range(16):
            target = self.new_temp_name(directory, prefix, area)
            try:
                os.mkdir(target, 0o700)
            except FileExistsError:
                continue
            self.writes += 1
            return target
        raise FileExistsError(f"could not create a temp dir under {directory}")

    def link(self, src: str | os.PathLike, dst: str | os.PathLike) -> str:
        """Hardlink ``src`` (a source-tree file or a v2 file; never modified) to a new name ``dst``
        in v2. ``src`` must be a regular file and is not followed if it is a symlink."""
        target = self.check(dst, "v2")
        s = self.check_link_source(src)
        st = os.lstat(s)
        if not stat.S_ISREG(st.st_mode):
            raise GuardError(f"link source {s!r} is not a regular file")
        os.link(s, target, follow_symlinks=False)
        self.writes += 1
        return target

    def symlink_in_scratch(self, src: str | os.PathLike, dst: str | os.PathLike) -> str:
        """Scratch-only symlink (7zz volume view). Creating a symlink never touches ``src``."""
        target = self.check(dst, "scratch")
        os.symlink(os.fspath(src), target)
        self.writes += 1
        return target

    def rename(self, src: str | os.PathLike, dst: str | os.PathLike, area: str = "v2") -> str:
        """Rename within one area. Both names are checked: a source-tree file is never renamed."""
        s = self.check(src, area)
        target = self.check(dst, area)
        os.rename(s, target)
        self.writes += 1
        return target

    def unlink(self, path: str | os.PathLike, area: str = "v2") -> None:
        """Remove one NAME (never follows a symlink). v2 / scratch only."""
        target = self.check(path, area)
        st = os.lstat(target)
        if stat.S_ISDIR(st.st_mode):
            raise IsADirectoryError(target)
        os.unlink(target)
        self.writes += 1

    def rmdir(self, path: str | os.PathLike, area: str = "v2") -> None:
        """Remove an EMPTY directory (gc only)."""
        target = self.check(path, area)
        os.rmdir(target)
        self.writes += 1

    def rmtree_scratch(self, path: str | os.PathLike) -> None:
        """Recursive delete, scratch only (spool / 7zz extraction dirs we created)."""
        target = self.check(path, "scratch")
        shutil.rmtree(target, ignore_errors=True)
        self.writes += 1

    # -------------------------------------------------------------------------- read primitives
    @staticmethod
    def open_read(path: str | os.PathLike) -> int:
        """Read-only fd (``O_RDONLY | O_NOFOLLOW``) — the only way materialize opens a file."""
        fd = os.open(os.fspath(path), READ_FLAGS)
        return fd


# ----------------------------------------------------------------------------- startup checks


@dataclass(frozen=True)
class StartupReport:
    v2_root: str
    source_root: str
    scratch_root: str | None
    same_device: bool
    source_readonly_mount: bool
    shared_mount_acknowledged: bool
    source_writable_by_uid: bool
    scratch_fstype: str | None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


# Indirection so tests can simulate mount layouts without root.
_stat = os.stat
_statvfs = os.statvfs


def open_guard(
    v2_root: str | os.PathLike,
    source_root: str | os.PathLike,
    scratch_root: str | os.PathLike | None = None,
    *,
    shared_mount_ack: bool = False,
    require_v2_exists: bool = True,
) -> tuple[WriteGuard, StartupReport]:
    """Validate the mount layout and return a guard. Raises :class:`StartupError` when unsafe.

    * every root absolute; v2, source and scratch pairwise disjoint (none inside another);
    * **AC4** — if source and v2 are on different filesystems, the source mount must be
      read-only (``ST_RDONLY``). If they share one filesystem (ADR D-6a: one NFS mount so
      ``link(source, v2)`` is legal), the operator must acknowledge that with
      ``FORGE_SOURCE_SHARED_MOUNT=1``; the guard is then the enforcement;
    * scratch must be local (not NFS/CIFS);
    * self-test: the guard refuses the source root and accepts v2.
    """
    raw = {"v2": v2_root, "source": source_root}
    if scratch_root is not None:
        raw["scratch"] = scratch_root
    for k, v in raw.items():
        if not os.path.isabs(os.fspath(v)):
            raise StartupError(f"{k} root must be absolute: {v!r}")
    v2 = os.path.realpath(os.fspath(v2_root))
    src = os.path.realpath(os.fspath(source_root))
    scr = os.path.realpath(os.fspath(scratch_root)) if scratch_root is not None else None
    if not os.path.isdir(src):
        raise StartupError(f"source root {src} is not a directory")
    if require_v2_exists and not os.path.isdir(v2):
        raise StartupError(f"v2 root {v2} is not a directory (create it once, by hand)")
    pairs = [("v2", v2, "source", src)]
    if scr is not None:
        pairs += [("scratch", scr, "source", src), ("scratch", scr, "v2", v2)]
    for an, a, bn, b in pairs:
        if _is_under_or_equal(a, b) or _is_under_or_equal(b, a):
            raise StartupError(f"{an} root {a} and {bn} root {b} overlap")
    scratch_fs = None
    if scr is not None:
        if not os.path.isdir(scr):
            raise StartupError(f"scratch {scr} is not a directory")
        scratch_fs = mount_fstype(scr)
        if scratch_fs in _NETWORK_FS or scratch_fs.startswith("nfs"):
            raise StartupError(f"scratch {scr} is on a network filesystem ({scratch_fs})")
    same_dev = require_v2_exists and _stat(src).st_dev == _stat(v2).st_dev
    ro = bool(_statvfs(src).f_flag & os.ST_RDONLY)
    if not ro:
        if not same_dev:
            raise StartupError(
                f"source root {src} is on a WRITABLE mount separate from v2 — mount it read-only "
                "(readOnly: true) or mount the Backups export root once (ADR D-6a)"
            )
        if not shared_mount_ack:
            raise StartupError(
                f"source root {src} shares a writable filesystem with v2 {v2}. That is the ADR "
                "D-6a layout (needed for hardlinks); acknowledge it with "
                "FORGE_SOURCE_SHARED_MOUNT=1 — the write guard is then the only enforcement"
            )
    guard = WriteGuard(v2_root=v2, source_root=src, scratch_root=scr)
    for probe in (src, os.path.join(src, "forge-guard-probe")):
        try:
            guard.check(probe, "v2")
        except GuardError:
            pass
        else:  # pragma: no cover - would be a guard bug
            raise StartupError("guard self-test failed: source path accepted")
    guard.check(os.path.join(v2, "forge-guard-probe"), "v2")
    report = StartupReport(
        v2_root=v2,
        source_root=src,
        scratch_root=scr,
        same_device=same_dev,
        source_readonly_mount=ro,
        shared_mount_acknowledged=shared_mount_ack,
        source_writable_by_uid=os.access(src, os.W_OK),
        scratch_fstype=scratch_fs,
    )
    return guard, report


def is_v2_relative_safe(rel: str) -> bool:
    """A plan-relative path is safe to join under v2: relative, no ``..``/``.``/empty parts."""
    if not rel or rel.startswith("/") or "\x00" in rel:
        return False
    return all(part not in ("", ".", "..") for part in rel.split("/"))


def join_v2(guard: WriteGuard, rel: str) -> Path:
    """``<v2>/<rel>`` for a plan path, refusing anything that is not a plain relative path."""
    if not is_v2_relative_safe(rel):
        raise GuardError(f"unsafe plan path {rel!r}")
    return Path(guard.v2_root) / rel
