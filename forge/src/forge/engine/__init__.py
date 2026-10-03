"""Library Forge archive engine (INIT-032/SPEC-006). Pure: reads files, calls a Sink; no DB.

``process(ref, sink, caps, scratch)`` makes one sequential streaming pass over a container and
reports every member (sha256, size, kind, STL triangles, depth) or a typed refusal/failure.
Archive containers are read in an isolated child process (address-space limit, own process
group, SIGKILL at ``wall_seconds + kill_grace_seconds``) so a hostile archive can only fail its
own container. See ``forge/tests/engine`` for the golden and hostile fixtures.
"""

from __future__ import annotations

import errno
import json
import os
import secrets
import select
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from forge.hashing import FileChangedError, hash_file_full

from .caps import Caps
from .fallback import find_7zz
from .kinds import MAGIC_BYTES, classify
from .types import ContainerRef, Result, Sink

__all__ = ["Caps", "ContainerRef", "Result", "Sink", "process"]

_NETWORK_FS = (
    "nfs",
    "nfs4",
    "cifs",
    "smb3",
    "smbfs",
    "fuse.sshfs",
    "9p",
    "ceph",
    "glusterfs",
)


def process(
    ref: ContainerRef,
    sink: Sink,
    caps: Caps | None = None,
    scratch: Path | None = None,
    *,
    isolate: bool = True,
) -> Result:
    """Process one container. Never raises for a bad archive (typed ``Result`` instead); raises
    ``ValueError`` for a misconfigured scratch dir and re-raises exceptions from the sink."""
    caps = caps or Caps()
    if ref.kind == "loose_batch":
        return _process_loose(ref, sink, caps)
    if ref.kind != "archive":
        raise ValueError(f"unknown container kind {ref.kind!r}")
    if not ref.paths:
        raise ValueError("archive container without paths")
    if scratch is None:
        scratch = Path(os.environ.get("FORGE_SCRATCH", "/scratch"))
    check_scratch(scratch, ref.paths)
    rundir = scratch / f"forge-run-{secrets.token_hex(8)}"
    rundir.mkdir(mode=0o700)
    try:
        if not isolate:
            from .archive import run_archive

            return run_archive(list(ref.paths), sink, caps, rundir, find_7zz())
        return _process_isolated(ref, sink, caps, rundir)
    finally:
        shutil.rmtree(rundir, ignore_errors=True)


# ------------------------------------------------------------------------------- scratch guard


def _mount_fstype(path: Path) -> str:
    best, fstype = "", ""
    try:
        with open("/proc/self/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mnt = parts[1].replace("\\040", " ")
                if (str(path) == mnt or str(path).startswith(mnt.rstrip("/") + "/")) and len(
                    mnt
                ) > len(best):
                    best, fstype = mnt, parts[2]
    except OSError:
        return ""
    return fstype


def check_scratch(scratch: Path, sources: tuple[Path, ...] | list[Path]) -> None:
    """Scratch must be an existing local directory outside the source tree."""
    real = scratch.resolve()
    if not real.is_dir():
        raise ValueError(f"scratch dir {scratch} does not exist")
    fstype = _mount_fstype(real)
    if fstype in _NETWORK_FS or fstype.startswith("nfs"):
        raise ValueError(f"scratch dir {scratch} is on a network filesystem ({fstype})")
    roots = [Path(os.environ.get("FORGE_SOURCE_ROOT", "/models"))] + [
        Path(p).parent for p in sources
    ]
    for root in roots:
        try:
            r = root.resolve()
        except OSError:
            continue
        if real == r or r in real.parents:
            raise ValueError(f"scratch dir {scratch} is inside the source tree {root}")


# ------------------------------------------------------------------------------ isolated reader


def _dispatch(sink: Sink, msg: list) -> Result | None:
    tag = msg[0]
    if tag == "m":
        _, chain, sha, size, kind, tri, depth = msg
        sink.member(tuple(chain), sha, size, kind, tri, depth)
    elif tag == "r":
        sink.refused(tuple(msg[1]), msg[2])
    elif tag == "n":
        sink.nested_archive(tuple(msg[1]), msg[2], msg[3])
    elif tag == "nr":
        sink.nested_result(tuple(msg[1]), Result.from_dict(msg[2]))
    elif tag == "done":
        return Result.from_dict(msg[1])
    else:
        raise RuntimeError(f"unknown worker message {tag!r}")
    return None


# The reader child parses hostile archives; it must never see pod secrets
# (FORGE_DB_URL, tokens, Vault-injected vars). Whitelist only.
_CHILD_ENV_ALLOW = ("PATH", "LANG", "LC_ALL", "FORGE_7ZZ", "FORGE_ENGINE_TEST_STALL_SECONDS")


def _child_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in _CHILD_ENV_ALLOW if k in os.environ}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])  # .../src containing forge/
    env.setdefault("LC_ALL", "C.UTF-8")
    return env


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _reap(proc: subprocess.Popen, deadline: float) -> tuple[int, int]:
    """Wait for the child (killing it at ``deadline``); returns (exit code, peak RSS KiB)."""
    while True:
        pid, status, ru = os.wait4(proc.pid, os.WNOHANG)
        if pid:
            proc.returncode = os.waitstatus_to_exitcode(status)
            return proc.returncode, ru.ru_maxrss
        if time.monotonic() > deadline:
            _kill(proc)
            deadline = float("inf")
        time.sleep(0.02)


def _process_isolated(ref: ContainerRef, sink: Sink, caps: Caps, rundir: Path) -> Result:
    req = {
        "paths": [str(p) for p in ref.paths],
        "caps": asdict(caps),
        "scratch": str(rundir),
        "sevenzip": find_7zz(),
    }
    r_fd, w_fd = os.pipe()
    started = time.monotonic()
    kill_at = started + caps.wall_seconds + caps.kill_grace_seconds
    proc = subprocess.Popen(
        [sys.executable, "-m", "forge.engine._worker", str(w_fd)],
        stdin=subprocess.PIPE,
        pass_fds=(w_fd,),
        start_new_session=True,
        env=_child_env(),
        cwd=rundir,
    )
    os.close(w_fd)
    result: Result | None = None
    killed_for_time = False
    try:
        proc.stdin.write(json.dumps(req).encode())
        proc.stdin.close()
        pending = b""
        eof = False
        while result is None and not eof:
            timeout = kill_at - time.monotonic()
            if timeout <= 0:
                killed_for_time = True
                _kill(proc)
                break
            ready, _, _ = select.select([r_fd], [], [], min(timeout, 5.0))
            if not ready:
                continue
            chunk = os.read(r_fd, 1 << 16)
            if not chunk:
                eof = True
            pending += chunk
            *lines, pending = pending.split(b"\n")
            for line in lines:
                if line:
                    result = _dispatch(sink, json.loads(line)) or result
    except BaseException:
        _kill(proc)
        raise
    finally:
        os.close(r_fd)
        code, rss = _reap(proc, time.monotonic() + (5 if result is not None else 0.5))
    if result is not None:
        return _with_rss(result, rss)
    if killed_for_time:
        return Result(
            "failed",
            "timeout",
            0,
            0,
            1,
            detail="reader killed at wall-time cap",
            peak_rss_kb=rss,
        )
    if code in (-signal.SIGKILL, 137):
        return Result(
            "failed",
            "oom",
            0,
            0,
            1,
            detail="reader SIGKILLed (OOM killer)",
            peak_rss_kb=rss,
        )
    return Result(
        "failed",
        "reader_error",
        0,
        0,
        1,
        detail=f"reader process exited {code}",
        peak_rss_kb=rss,
    )


def _with_rss(res: Result, rss: int) -> Result:
    d = res.to_dict()
    d["peak_rss_kb"] = rss
    return Result.from_dict(d)


# ---------------------------------------------------------------------------------- loose batch


def _process_loose(ref: ContainerRef, sink: Sink, caps: Caps) -> Result:
    deadline = time.monotonic() + caps.wall_seconds
    members = bytes_read = failures = 0
    for path in ref.paths:
        chain = (str(path),)
        if time.monotonic() > deadline:
            return Result("failed", "timeout", members, bytes_read, 0, reader="loose")
        try:
            sha, size, tri, head = hash_file_full(path, head_bytes=MAGIC_BYTES, deadline=deadline)
        except FileNotFoundError:
            sink.refused(chain, "vanished")
            continue
        except TimeoutError:
            return Result("failed", "timeout", members, bytes_read, 0, reader="loose")
        except IsADirectoryError:
            sink.refused(chain, "not_regular")
            continue
        except FileChangedError:
            sink.refused(chain, "reader_error")
            failures += 1
            continue
        except OSError as x:
            if x.errno == errno.ELOOP:
                sink.refused(chain, "symlink")
                continue
            sink.refused(chain, "reader_error")
            failures += 1
            continue
        sink.member(chain, sha, size, classify(Path(path).name, head), tri, 0)
        members += 1
        bytes_read += size
    if members == 0 and failures > 0:
        return Result(
            "failed",
            "reader_error",
            0,
            0,
            0,
            reader="loose",
            detail=f"{failures} unreadable",
        )
    return Result("done", None, members, bytes_read, 0, reader="loose")
