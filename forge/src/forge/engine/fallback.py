"""Fallback readers: official static ``7zz`` (RAR4 CRC failures, Deflate64, exotic 7z filters)
and the gzip/bz2/lzma stream modules for single-file ``.gz/.bz2/.xz`` (a one-member container).

7zz is run with an argv list (no shell), stdin closed, its own process group, a timeout, and an
output directory that is a fresh random dir under the per-run scratch dir. Every extracted
member is verified (regular file, listed size, listed CRC32) before it is hashed into the sink;
the extraction dir is removed in ``finally``. Symlinks are never followed.
"""

from __future__ import annotations

import bz2
import gzip
import lzma
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import zlib
from pathlib import Path
from typing import TYPE_CHECKING

from .caps import FatalFailure, LocalFailure
from .refuse import check_name, display_name

if TYPE_CHECKING:
    from .archive import ContainerState, Ctx

_DUMMY_PASSWORD = "-pforge-no-password"
_STREAM_SUFFIX = {"gzip": (".gz", ".gzip"), "bzip2": (".bz2",), "xz": (".xz",)}
_UNIX_MODE = re.compile(r"^[-dlcbps][-rwxsStT]{9}$")


def find_7zz() -> str | None:
    explicit = os.environ.get("FORGE_7ZZ")
    if explicit:
        return explicit if os.access(explicit, os.X_OK) else None
    return shutil.which("7zz")


def _safe_basename(name: str, default: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "_", base).strip()
    return base if base not in ("", ".", "..") else default


# ---------------------------------------------------------------------------- stream modules


class _Concat:
    """Read-only concatenation of files (raw split volumes) with a consumed-bytes counter."""

    def __init__(self, paths: list[Path]) -> None:
        self._paths = list(paths)
        self._f = None
        self.consumed = 0

    def readable(self) -> bool:
        return True

    def read(self, n: int = -1) -> bytes:
        while True:
            if self._f is None:
                if not self._paths:
                    return b""
                self._f = open(self._paths.pop(0), "rb")  # noqa: SIM115 - closed in read()/close()
            data = self._f.read(n if n is not None and n >= 0 else 1 << 20)
            if data:
                self.consumed += len(data)
                return data
            self._f.close()
            self._f = None

    def close(self) -> None:
        if self._f is not None:
            self._f.close()
            self._f = None


def stream_member_name(name_hint: str, fmt: str) -> str:
    base = _safe_basename(name_hint, "data")
    low = base.lower()
    if fmt == "gzip" and low.endswith(".tgz"):
        return base[:-4] + ".tar"
    for suffix in _STREAM_SUFFIX.get(fmt, ()):
        if low.endswith(suffix) and len(base) > len(suffix):
            return base[: -len(suffix)]
    return base + ".data" if "." not in base else base.rsplit(".", 1)[0]


def _open_stream(fmt: str, raw):
    if fmt == "gzip":
        return gzip.GzipFile(fileobj=raw, mode="rb")
    if fmt == "bzip2":
        return bz2.BZ2File(raw)
    return lzma.LZMAFile(raw)


def peek_stream(paths: list[Path], fmt: str, n: int) -> bytes | None:
    """First ``n`` decompressed bytes of a gzip/bzip2/xz stream, ``None`` if undecodable."""
    raw = _Concat(paths)
    try:
        with _open_stream(fmt, raw) as z:
            return z.read(n)
    except (EOFError, OSError, lzma.LZMAError, zlib.error, ValueError):
        return None
    finally:
        raw.close()


def read_stream(ctx: Ctx, st: ContainerState, paths: list[Path], fmt: str) -> None:
    from .archive import MemberWriter

    norm, why = check_name(stream_member_name(st.name_hint, fmt))
    if why is not None:  # pragma: no cover - _safe_basename already sanitizes
        norm = "data"
    raw = _Concat(paths)
    w = MemberWriter(ctx, st, norm)
    try:
        with _open_stream(fmt, raw) as z:
            while True:
                data = z.read(1 << 20)
                if not data:
                    break
                w.feed(memoryview(data), raw.consumed)
    except (EOFError, OSError, lzma.LZMAError, zlib.error, ValueError) as x:
        w.abort()
        raise LocalFailure(
            "reader_error", f"{fmt}: {type(x).__name__}: {x}"[:300]
        ) from None
    except BaseException:
        w.abort()
        raise
    finally:
        raw.close()
    w.finish()


# ---------------------------------------------------------------------------------- 7zz


def _run(ctx: Ctx, argv: list[str], timeout: float) -> subprocess.CompletedProcess:
    env = {
        "PATH": "/usr/bin:/bin",
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
        "HOME": str(ctx.scratch),
    }
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=ctx.scratch,
        env=env,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=max(1.0, timeout))
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise FatalFailure("timeout", "7zz exceeded the wall-time cap") from None
    except BaseException:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise
    return subprocess.CompletedProcess(argv, proc.returncode, out, err)


def parse_slt(text: str) -> list[dict[str, str]]:
    """Entries of ``7zz l -slt`` output (blocks after the ``----------`` separator)."""
    _, sep, body = text.partition("\n----------\n")
    if not sep:
        return []
    entries, cur = [], {}
    for line in body.splitlines():
        if not line.strip():
            if cur:
                entries.append(cur)
                cur = {}
            continue
        k, eq, v = line.partition(" = ")
        if eq:
            cur[k.strip()] = v
        elif line.endswith(" ="):
            cur[line[:-2].strip()] = ""
    if cur:
        entries.append(cur)
    return [e for e in entries if "Path" in e]


def entry_type(e: dict[str, str]) -> str:
    """``dir``, ``file``, or a refusal reason."""
    if e.get("Folder") == "+":
        return "dir"
    if e.get("Alternate Stream") == "+":
        return "not_regular"
    if e.get("Symbolic Link"):
        return "symlink"
    if e.get("Hard Link") or e.get("Copy Link"):
        return "hardlink"
    tokens = e.get("Attributes", "").split()
    for tok in tokens:
        if _UNIX_MODE.match(tok):
            t = tok[0]
            return {
                "-": "file",
                "d": "dir",
                "l": "symlink",
                "c": "device",
                "b": "device",
                "p": "fifo",
                "s": "socket",
            }[t]
    if tokens and "D" in tokens[0] and not _UNIX_MODE.match(tokens[0]):
        return "dir"
    return "file"


def _seven_zip_reason(rc: int, err: str, default: str = "reader_error") -> str:
    """Typed reason from 7zz **stderr** (never the ``-slt`` listing, which says ``Encrypted = -``)."""
    low = err.lower()
    if (
        "wrong password" in low
        or "can not open encrypted archive" in low
        or "cannot open encrypted" in low
    ):
        return "encrypted"
    if "missing volume" in low:
        return "missing_volume"
    if rc == 8 or "can't allocate" in low or "not enough memory" in low:
        return "oom"
    if "cannot open the file as archive" in low or "unsupported" in low:
        return "unsupported_format"
    return default


def read_7zz(ctx: Ctx, st: ContainerState, paths: list[Path]) -> None:
    """Re-read a container with 7zz after libarchive failed, skipping members a previous pass
    already recorded (``st.handled``)."""
    from .archive import MemberWriter, refuse

    exe = ctx.sevenzip
    if not exe:
        raise LocalFailure("reader_error", "7zz unavailable")
    linkdir = Path(tempfile.mkdtemp(prefix="vol-", dir=ctx.scratch))
    outdir = Path(tempfile.mkdtemp(prefix="x-", dir=ctx.scratch))
    reserved = 0
    try:
        # Volumes are presented under their own basenames in a private dir, so 7zz can find
        # exactly this volume set and nothing else.
        names = []
        for i, p in enumerate(paths):
            hint = st.name_hint if len(paths) == 1 else p.name
            link = linkdir / _safe_basename(hint, f"volume{i}")
            os.symlink(os.path.abspath(p), link)
            names.append(link)
        first = str(names[0])
        common = ["-sccUTF-8", "-scsUTF-8", _DUMMY_PASSWORD, "-bd"]
        listed = _run(
            ctx,
            [exe, "l", "-slt", *common, "--", first],
            ctx.budget.remaining_seconds(),
        )
        out = listed.stdout.decode("utf-8", "backslashreplace")
        err = listed.stderr.decode("utf-8", "backslashreplace")
        if listed.returncode != 0:
            raise LocalFailure(
                _seven_zip_reason(listed.returncode, err),
                f"7zz l rc={listed.returncode}: {err.strip()[:200]}",
            )
        entries = parse_slt(out)
        if any(e.get("Encrypted") == "+" for e in entries):
            raise LocalFailure("encrypted", "7zz lists encrypted members")
        # Plan first: (entry, normalized name, refusal reason) for everything not yet handled.
        plan: list[tuple[dict, str | None, str | None]] = []
        for e in entries:
            kind = entry_type(e)
            if kind == "dir":
                continue
            norm, why = check_name(e["Path"])
            if why is None and kind != "file":
                why = kind
            key = norm if why is None else "!" + display_name(e["Path"])
            if st.handled[key] > 0:
                st.handled[key] -= 1
                st.seen[key] += 1
                continue
            if why is None:
                ctx.budget.check_member(int(e.get("Size") or 0), None)
            plan.append((e, norm, why))
        wanted = [e for e, _, why in plan if why is None]
        total = sum(int(e.get("Size") or 0) for e in wanted)
        if not ctx.budget.reserve_spool(total):
            raise LocalFailure(
                "spool_exceeded", f"7zz extraction needs {total} bytes of scratch"
            )
        reserved = total
        ctx.budget.check_container(total, st.compressed)
        rc, x_err = 0, ""
        if wanted:
            # Extract ONLY regular files with safe names (exact names, no wildcards): link,
            # device and hostile entries are never materialised, even on scratch.
            listfile = linkdir / ".include"
            listfile.write_text("".join(e["Path"] + "\n" for e in wanted), "utf-8")
            extracted = _run(
                ctx,
                [exe, "x", "-y", *common, "-mmt=1", "-spd", f"-i@{listfile}"]
                + [f"-o{outdir}", "--", first],
                ctx.budget.remaining_seconds(),
            )
            rc = extracted.returncode
            x_err = extracted.stderr.decode("utf-8", "backslashreplace")
        bad: list[str] = []
        for e, norm, why in plan:
            if why is not None:
                refuse(ctx, st, e["Path"], why)
                continue
            if not _hash_extracted(ctx, st, outdir, norm, e, MemberWriter, rc == 0):
                bad.append(norm)
        if bad or rc != 0:
            raise LocalFailure(
                _seven_zip_reason(rc, x_err),
                f"7zz x rc={rc}; unverified={bad[:5]}; {x_err.strip()[:200]}",
            )
    finally:
        shutil.rmtree(outdir, ignore_errors=True)
        shutil.rmtree(linkdir, ignore_errors=True)
        ctx.budget.release_spool(reserved)


def _hash_extracted(
    ctx: Ctx,
    st: ContainerState,
    outdir: Path,
    norm: str,
    e: dict,
    writer_cls,
    clean_exit: bool,
) -> bool:
    """Hash one extracted file into the sink only if it matches the listing; delete it after."""
    path = outdir / norm
    try:
        real = path.resolve(strict=True)
        if outdir.resolve() not in real.parents:
            return False
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return False
    w = writer_cls(ctx, st, norm, existing=path)
    crc = 0
    try:
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                w.abort()
                return False
            while True:
                data = f.read(1 << 20)
                if not data:
                    break
                crc = zlib.crc32(data, crc)
                w.feed(memoryview(data))
        listed_size = e.get("Size")
        listed_crc = e.get("CRC") or ""
        if listed_size not in (None, "") and int(listed_size) != w.size:
            w.abort()
            return False
        if listed_crc and int(listed_crc, 16) != crc:
            w.abort()
            return False
        if not listed_crc and w.size and not clean_exit:
            w.abort()  # no listed CRC and 7zz reported errors: unverifiable, never a blob
            return False
        w.finish()
        return True
    except BaseException:
        w.abort()
        raise
    finally:
        path.unlink(missing_ok=True)
