"""Isolated reader process: ``python -m forge.engine._worker <fd>`` with a JSON request on stdin.

Sends one JSON line per sink call on ``fd`` and a final ``["done", result]``. The parent owns the
real sink, the wall-clock kill-switch and the scratch run dir.
"""

from __future__ import annotations

import json
import os
import resource
import sys
import time
from pathlib import Path

from .caps import Caps
from .types import Result


class LineSink:
    def __init__(self, out) -> None:
        self._out = out

    def _send(self, *msg) -> None:
        self._out.write(json.dumps(msg, ensure_ascii=True) + "\n")
        self._out.flush()

    def member(self, chain, sha256, size, kind, triangles, depth) -> None:
        self._send("m", list(chain), sha256, size, kind, triangles, depth)

    def refused(self, chain, reason) -> None:
        self._send("r", list(chain), reason)

    def nested_archive(self, chain, sha256, size) -> None:
        self._send("n", list(chain), sha256, size)

    def nested_result(self, chain, result: Result) -> None:
        self._send("nr", list(chain), result.to_dict())


def _limit_resources(caps: Caps) -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if caps.memory_bytes > 0:
        resource.setrlimit(resource.RLIMIT_AS, (caps.memory_bytes, caps.memory_bytes))


def main(argv: list[str]) -> int:
    out = os.fdopen(int(argv[1]), "w", encoding="ascii")
    req = json.loads(sys.stdin.read())
    caps = Caps(**req["caps"])
    from . import (
        _libarchive,  # noqa: F401 - map libarchive.so before the address-space limit
    )
    from .archive import run_archive

    _limit_resources(caps)
    stall = os.environ.get("FORGE_ENGINE_TEST_STALL_SECONDS")
    if stall:  # tests only: simulate a reader stuck inside one libarchive call
        time.sleep(float(stall))
    sink = LineSink(out)
    try:
        res = run_archive(
            [Path(p) for p in req["paths"]],
            sink,
            caps,
            Path(req["scratch"]),
            req.get("sevenzip"),
        )
    except MemoryError:
        res = Result("failed", "oom", 0, 0, 1, detail="MemoryError in reader")
    sink._send("done", res.to_dict())
    out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
