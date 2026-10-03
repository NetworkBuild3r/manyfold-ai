"""Streaming SHA-256 and STL triangle counting (pure; shared by walker and engine).

Nothing here holds a whole file in memory: data is consumed in fixed-size chunks.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

CHUNK = 8 << 20

_FACET = b"facet normal"
_BINARY_HEADER = 84
_BINARY_FACET = 50


class StlCounter:
    """Incremental STL triangle counter.

    Binary STL: uint32 little-endian at byte 80, accepted only when the total size is exactly
    ``84 + 50 * n``. ASCII STL (starts with ``solid``): occurrences of ``facet normal``
    (case-insensitive), counted across chunk boundaries. Anything else yields ``None``.
    """

    __slots__ = ("_ascii", "_facets", "_head", "_size", "_tail")

    def __init__(self) -> None:
        self._head = bytearray()
        self._tail = b""
        self._ascii: bool | None = None
        self._facets = 0
        self._size = 0

    def feed(self, data: bytes | bytearray | memoryview) -> None:
        n = len(data)
        if not n:
            return
        self._size += n
        if len(self._head) < _BINARY_HEADER:
            self._head += bytes(data[: _BINARY_HEADER - len(self._head)])
        if self._ascii is None:
            stripped = bytes(self._head).lstrip()
            if len(stripped) >= 5 or len(self._head) >= _BINARY_HEADER:
                self._ascii = stripped[:5].lower() == b"solid"
        if self._ascii is False:
            return
        # Undecided (tiny head so far) or ASCII candidate: scan.
        window = self._tail + bytes(data).lower()
        self._facets += window.count(_FACET)
        # A tail one byte shorter than the pattern cannot hold a whole match: nothing counts twice.
        self._tail = window[-(len(_FACET) - 1) :]

    def result(self) -> int | None:
        if len(self._head) >= _BINARY_HEADER:
            n = int.from_bytes(self._head[80:84], "little")
            if self._size == _BINARY_HEADER + _BINARY_FACET * n:
                return n
        if self._ascii and self._facets > 0:
            return self._facets
        return None


def is_stl_name(name: str) -> bool:
    return name.lower().endswith(".stl")


def sha256_stream(fileobj, chunk: int = CHUNK) -> tuple[str, int]:
    """SHA-256 hex digest and byte count of a binary file object, read in ``chunk`` pieces."""
    h = hashlib.sha256()
    size = 0
    while True:
        block = fileobj.read(chunk)
        if not block:
            break
        h.update(block)
        size += len(block)
    return h.hexdigest(), size


class FileChangedError(OSError):
    """The file's size changed while it was being read; the digest would not describe it."""


def _hash_open_fd(
    fd: int, count_triangles: bool, head_bytes: int, deadline: float | None
):
    import time

    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        raise IsADirectoryError(f"not a regular file (mode {st.st_mode:o})")
    h = hashlib.sha256()
    counter = StlCounter() if count_triangles else None
    head = bytearray()
    size = 0
    with os.fdopen(fd, "rb", buffering=0, closefd=False) as f:
        while True:
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError("wall time exceeded while hashing")
            block = f.read(CHUNK)
            if not block:
                break
            h.update(block)
            size += len(block)
            if len(head) < head_bytes:
                head += block[: head_bytes - len(head)]
            if counter is not None:
                counter.feed(block)
    if size != st.st_size or os.fstat(fd).st_size != st.st_size:
        raise FileChangedError(f"size changed during read ({st.st_size} -> {size})")
    return h.hexdigest(), size, (counter.result() if counter else None), bytes(head)


def hash_file_full(
    path: Path | str, *, head_bytes: int = 0, deadline: float | None = None
) -> tuple[str, int, int | None, bytes]:
    """Like :func:`hash_file` but also returns the first ``head_bytes`` bytes (for magic sniffing).

    Opens with ``O_NOFOLLOW | O_NONBLOCK`` so a symlink raises ``OSError(ELOOP)`` and a FIFO
    never blocks; anything that is not a regular file raises ``IsADirectoryError``.
    """
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        return _hash_open_fd(fd, is_stl_name(str(path)), head_bytes, deadline)
    finally:
        os.close(fd)


def hash_file(path: Path | str) -> tuple[str, int, int | None]:
    """``(sha256_hex, size, stl_triangles | None)`` for a loose file, streamed in 8 MiB chunks.

    Triangles are counted only for ``*.stl`` names.
    """
    sha, size, tri, _ = hash_file_full(path)
    return sha, size, tri
