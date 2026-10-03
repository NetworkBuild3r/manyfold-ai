"""hashing.py (STL counter, hash_file) and the loose_batch container kind."""

from __future__ import annotations

import errno
import hashlib
import os
import random

import pytest

from forge.engine import Caps, ContainerRef, process
from forge.hashing import StlCounter, hash_file, hash_file_full

from .conftest import RecordingSink


def _binary_stl(n: int, extra: bytes = b"") -> bytes:
    return (
        b"solid but binary".ljust(80, b"\0")
        + n.to_bytes(4, "little")
        + os.urandom(50 * n)
        + extra
    )


def _ascii_stl(n: int) -> bytes:
    facet = "facet normal 0 0 1\n outer loop\n vertex 0 0 0\n vertex 1 0 0\n vertex 0 1 0\n endloop\nendfacet\n"
    return ("solid t\n" + facet * n + "endsolid t\n").encode()


def _count(data: bytes, pieces: int, seed: int = 0) -> int | None:
    rnd = random.Random(seed)
    cuts = sorted(rnd.sample(range(1, len(data)), min(pieces, len(data) - 1)))
    c = StlCounter()
    prev = 0
    for cut in [*cuts, len(data)]:
        c.feed(data[prev:cut])
        prev = cut
    return c.result()


@pytest.mark.parametrize("pieces", [1, 7, 500])
def test_binary_stl_count(pieces):
    assert _count(_binary_stl(37), pieces) == 37


@pytest.mark.parametrize("pieces", [1, 3, 997])
def test_ascii_stl_count_across_chunk_boundaries(pieces):
    assert _count(_ascii_stl(123), pieces, seed=pieces) == 123


def test_ascii_stl_byte_by_byte_and_uppercase():
    data = _ascii_stl(5).replace(b"facet normal", b"FACET NORMAL")
    c = StlCounter()
    for i in range(len(data)):
        c.feed(data[i : i + 1])
    assert c.result() == 5


def test_binary_size_mismatch_is_none():
    assert _count(_binary_stl(10, extra=b"x"), 3) is None
    assert _count(b"not an stl at all" * 10, 2) is None
    assert StlCounter().result() is None


def test_hash_file(tmp_path):
    data = _binary_stl(9)
    p = tmp_path / "Part.STL"
    p.write_bytes(data)
    assert hash_file(p) == (hashlib.sha256(data).hexdigest(), len(data), 9)
    q = tmp_path / "notes.txt"
    q.write_bytes(_ascii_stl(3))
    assert hash_file(q)[2] is None  # triangles only for *.stl


def test_hash_file_refuses_symlink_and_fifo(tmp_path):
    target = tmp_path / "t.stl"
    target.write_bytes(_ascii_stl(1))
    link = tmp_path / "l.stl"
    link.symlink_to(target)
    with pytest.raises(OSError) as exc:
        hash_file(link)
    assert exc.value.errno == errno.ELOOP
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(IsADirectoryError):
        hash_file_full(fifo)  # returns immediately: O_NONBLOCK, never blocks on a FIFO


def _loose(paths):
    sink = RecordingSink()
    res = process(ContainerRef("loose_batch", tuple(paths), "batch"), sink, Caps())
    return res, sink


def test_loose_batch(tmp_path):
    a = tmp_path / "a.stl"
    a.write_bytes(_binary_stl(4))
    b = tmp_path / "b.png"
    b.write_bytes(b"\x89PNG" + os.urandom(100))
    z = tmp_path / "c.dat"
    z.write_bytes(b"PK\x03\x04" + os.urandom(64))
    fake = tmp_path / "model_file.bin.gz"
    fake.write_bytes(b"\x8c\xfd\n\xf5" + os.urandom(64))  # named .gz, not gzip
    gone = tmp_path / "gone.stl"
    link = tmp_path / "link.stl"
    link.symlink_to(a)
    res, sink = _loose([a, b, z, fake, gone, link])
    assert (res.status, res.members, res.max_depth) == ("done", 4, 0)
    got = {m[0]: m for m in sink.members}
    assert got[(str(a),)][3:] == ("mesh", 4, 0)
    assert got[(str(b),)][3] == "image"
    assert got[(str(z),)][3] == "archive"  # by magic
    assert got[(str(fake),)][3] == "other"  # archive extension, no signature
    assert got[(str(a),)][1] == hashlib.sha256(a.read_bytes()).hexdigest()
    assert dict(sink.refusals) == {(str(gone),): "vanished", (str(link),): "symlink"}
    assert sink.nested == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads mode-000 files")
def test_loose_batch_partial_and_total_read_errors(tmp_path):
    ok = tmp_path / "ok.obj"
    ok.write_bytes(b"v 0 0 0\n")
    bad = tmp_path / "bad.stl"
    bad.write_bytes(b"x")
    bad.chmod(0)
    res, sink = _loose([ok, bad])
    assert (res.status, res.members) == ("done", 1)
    assert sink.refusals == [((str(bad),), "reader_error")]
    res, sink = _loose([bad, tmp_path / "missing.stl"])
    assert (res.status, res.reason) == ("failed", "reader_error")
    assert sink.members == []
