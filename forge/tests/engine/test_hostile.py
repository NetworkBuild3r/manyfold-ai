"""AC2-AC6 — bombs, depth cap, traversal/link/device refusal, truncation, RSS, kill-switch."""

from __future__ import annotations

import gzip
import io
import os
import resource
import tarfile
import time
import zipfile
from pathlib import Path

import pytest

from forge.engine import Caps, ContainerRef, process

from .conftest import (
    FIXTURES,
    MANIFEST,
    copy_fixture,
    needs_7zz,
    run,
    tree_snapshot,
    zeros_zip,
    zip_files,
)

GIB = 1 << 30
# ADR D-6a worker memory limit.
WORKER_MEMORY_LIMIT_KB = 2 * 1024 * 1024


def _names(sink) -> set[str]:
    return {"/".join(m[0]) for m in sink.members}


# --------------------------------------------------------------------------------- AC2 bombs


def test_one_gib_zero_member_fails_ratio_fast(src, scratch):
    bomb = zeros_zip(src / "zeros.zip")
    assert bomb.stat().st_size < 2 << 20
    t0 = time.monotonic()
    res, sink = run([bomb], scratch_dir=scratch)
    elapsed = time.monotonic() - t0
    assert (res.status, res.reason) == ("failed", "ratio_exceeded"), res
    assert sink.members == []  # no blob for the offending member (GR-004)
    assert elapsed < 30, elapsed
    assert res.peak_rss_kb < WORKER_MEMORY_LIMIT_KB


def test_one_gib_zero_member_too_large_by_header(src, scratch):
    bomb = zeros_zip(src / "zeros.zip")
    caps = Caps(ratio=10**9, member_bytes=64 << 20)
    res, sink = run([bomb], caps=caps, scratch_dir=scratch)
    assert (res.status, res.reason) == ("failed", "member_too_large"), res
    assert sink.members == []


def test_member_too_large_while_streaming(src, scratch):
    """No declared size (gzip stream): the cap trips mid-member, not after."""
    p = src / "zeros.bin.gz"
    with gzip.open(p, "wb", compresslevel=1) as g:
        chunk = b"\0" * (1 << 20)
        for _ in range(96):
            g.write(chunk)
    res, sink = run(
        [p], caps=Caps(ratio=10**9, member_bytes=32 << 20), scratch_dir=scratch
    )
    assert (res.status, res.reason) == ("failed", "member_too_large"), res
    assert sink.members == []


def _nest(leaf: bytes, levels: int, copies: int) -> bytes:
    data = leaf
    for depth in range(levels):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for i in range(copies):
                z.writestr(f"l{depth}_{i:x}.zip", data)
        data = buf.getvalue()
    return data


def test_42zip_shape_stopped_by_depth_cap(src, scratch, tmp_path):
    """42.zip's shape (16 copies x 5 levels of zips over a zero-filled leaf): the zeros sit at
    depth 6, so nothing below depth 3 is ever opened and no bomb byte is decompressed."""
    leaf = zeros_zip(tmp_path / "leaf.zip", size=64 << 20).read_bytes()
    top = src / "42.zip"
    top.write_bytes(_nest(leaf, 4, 16))
    t0 = time.monotonic()
    res, sink = run([top], scratch_dir=scratch)
    assert time.monotonic() - t0 < 60
    assert not any(m[0][-1] == "zeros.bin" for m in sink.members)
    deepest = [r for c, r in sink.nested_results.items() if len(c) == 3]
    assert deepest and all(
        (r.status, r.reason) == ("failed", "depth_exceeded") for r in deepest
    )
    assert res.max_depth == 3


def test_reachable_nested_bomb_fails_whole_tree(src, scratch, tmp_path):
    """Zero-filled leaves reachable at depth 3: the first one trips ratio_exceeded and the
    whole source archive fails with it; the bomb member has no blob."""
    leaf = zeros_zip(tmp_path / "leaf.zip", size=256 << 20).read_bytes()
    top = src / "bomb.zip"
    top.write_bytes(_nest(leaf, 2, 16))
    t0 = time.monotonic()
    res, sink = run([top], scratch_dir=scratch)
    assert (res.status, res.reason) == ("failed", "ratio_exceeded"), res
    assert time.monotonic() - t0 < 60
    assert not any(m[0][-1] == "zeros.bin" for m in sink.members)
    on_path = [r for r in sink.nested_results.values() if r.status == "failed"]
    assert on_path and all(r.reason == "ratio_exceeded" for r in on_path)


# ------------------------------------------------------------------------------ AC3 depth cap


def test_depth4_child_fails_depth_exceeded(src, scratch, tmp_path):
    d4 = zip_files(
        tmp_path / "d4.zip",
        {"deep.stl": b"solid x\nfacet normal 0 0 1\nendsolid\n", "level4.txt": b"4"},
    )
    d3 = zip_files(tmp_path / "d3.zip", {"d4.zip": d4.read_bytes(), "level3.txt": b"3"})
    d2 = zip_files(tmp_path / "d2.zip", {"d3.zip": d3.read_bytes(), "level2.txt": b"2"})
    d1 = zip_files(src / "d1.zip", {"d2.zip": d2.read_bytes(), "level1.txt": b"1"})
    res, sink = run([d1], scratch_dir=scratch)
    assert res.status == "done" and res.max_depth == 3, res
    assert _names(sink) == {
        "d2.zip",
        "level1.txt",
        "d2.zip/d3.zip",
        "d2.zip/level2.txt",
        "d2.zip/d3.zip/d4.zip",
        "d2.zip/d3.zip/level3.txt",
    }
    depths = {"/".join(m[0]): m[5] for m in sink.members}
    assert (
        depths["level1.txt"] == 1
        and depths["d2.zip/level2.txt"] == 2
        and depths["d2.zip/d3.zip/level3.txt"] == 3
    )
    child = sink.nested_results[("d2.zip", "d3.zip", "d4.zip")]
    assert (child.status, child.reason) == ("failed", "depth_exceeded")
    assert sink.nested_results[("d2.zip", "d3.zip")].status == "done"
    assert ("d2.zip", "d3.zip", "d4.zip") in {n[0] for n in sink.nested}


# --------------------------------------------------------------------------- AC4 traversal etc


def _hostile_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name in [
            "../evil.txt",
            "/etc/evil.txt",
            "C:\\evil.txt",
            "..\\evil2.txt",
            "a/../../evil3.txt",
            "bad\x01name.txt",
        ]:
            z.writestr(zipfile.ZipInfo(name), b"pwned")
        link = zipfile.ZipInfo("link_to_passwd")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        z.writestr(link, "/etc/passwd")
        z.writestr(
            zipfile.ZipInfo("ok/model.stl"),
            b"solid a\nfacet normal 0 0 1\nendsolid a\n",
        )
    return path


def test_traversal_and_symlink_members_refused(src, scratch, tmp_path):
    hostile = _hostile_zip(src / "hostile.zip")
    hostile.chmod(0o444)
    before = tree_snapshot(tmp_path, skip=scratch)
    res, sink = run([hostile], scratch_dir=scratch)
    assert res.status == "done", res
    assert _names(sink) == {"ok/model.stl"}
    reasons = {c[-1]: r for c, r in sink.refusals}
    assert reasons == {
        "../evil.txt": "parent_traversal",
        "/etc/evil.txt": "absolute_path",
        "C:/evil.txt": "absolute_path",  # libarchive reports Windows separators as "/"
        "../evil2.txt": "parent_traversal",
        "a/../../evil3.txt": "parent_traversal",
        "bad\\x01name.txt": "control_chars",
        "link_to_passwd": "symlink",
    }
    assert tree_snapshot(tmp_path, skip=scratch) == before
    for p in (
        tmp_path / "evil.txt",
        tmp_path.parent / "evil.txt",
        src.parent / "evil3.txt",
    ):
        assert not p.exists()


def test_tar_link_device_fifo_members_refused(src, scratch):
    p = src / "special.tar"
    with tarfile.open(p, "w") as t:

        def add(name, type_, data=b"", linkname=""):
            ti = tarfile.TarInfo(name)
            ti.type = type_
            ti.size = len(data)
            ti.linkname = linkname
            if type_ in (tarfile.CHRTYPE, tarfile.BLKTYPE):
                ti.devmajor, ti.devminor = 1, 3
            t.addfile(ti, io.BytesIO(data) if data else None)

        add("real.txt", tarfile.REGTYPE, b"hello")
        add("sym", tarfile.SYMTYPE, linkname="/etc/shadow")
        add("hard", tarfile.LNKTYPE, linkname="real.txt")
        add("null", tarfile.CHRTYPE)
        add("disk", tarfile.BLKTYPE)
        add("pipe", tarfile.FIFOTYPE)
    res, sink = run([p], scratch_dir=scratch)
    assert res.status == "done", res
    assert _names(sink) == {"real.txt"}
    assert {c[-1]: r for c, r in sink.refusals} == {
        "sym": "symlink",
        "hard": "hardlink",
        "null": "device",
        "disk": "device",
        "pipe": "fifo",
    }


# -------------------------------------------------------------------------- AC6 truncation


def _truncate(src_path: Path, dst: Path, keep: float) -> Path:
    data = src_path.read_bytes()
    dst.write_bytes(data[: int(len(data) * keep)])
    return dst


@pytest.mark.parametrize(
    ("fixture", "manifest_key", "keep"),
    [
        ("split_raw.7z.001", "split_raw.7z", 1.0),  # first raw volume alone
        ("basic_rar4.rar", "basic_rar4.rar", 0.6),
        ("basic_lzma2.7z", "basic_lzma2.7z", 0.6),
        ("basic_rar5_solid.rar", "basic_rar5_solid.rar", 0.6),
        ("basic.zip", "basic.zip", 0.6),
    ],
)
def test_truncated_archive_reader_error(fixture, manifest_key, keep, src, scratch):
    p = _truncate(
        FIXTURES / fixture, src / ("trunc_" + fixture.replace(".001", "")), keep
    )
    res, sink = run([p], scratch_dir=scratch)
    assert (res.status, res.reason) == ("failed", "reader_error"), res
    expected = {
        tuple(m["chain"]): (m["sha256"], m["size"])
        for m in MANIFEST[manifest_key]["members"]
    }
    got = {m[0]: (m[1], m[2]) for m in sink.members}
    # Whatever was recorded is byte-exact; the truncated member(s) are absent (GR-004).
    assert all(expected[c] == v for c, v in got.items()), got
    assert set(got) < set(expected)


def test_truncated_zip_mid_member_has_no_blob(src, scratch, tmp_path):
    big = os.urandom(200_000)
    z = zip_files(
        tmp_path / "t.zip",
        {"first.txt": b"complete", "big.bin": big},
        zipfile.ZIP_STORED,
    )
    p = _truncate(z, src / "trunc.zip", 0.5)
    res, sink = run([p], scratch_dir=scratch)
    assert (res.status, res.reason) == ("failed", "reader_error"), res
    assert set(sink.by_chain()) == {
        ("first.txt",)
    }  # earlier member stays, truncated one absent


# ---------------------------------------------------------------------- typed reader failures


@pytest.mark.parametrize("fixture", ["encrypted.7z", "encrypted.zip"])
def test_encrypted(fixture, src, scratch):
    res, sink = run(copy_fixture([fixture], src), scratch_dir=scratch)
    assert (res.status, res.reason) == ("failed", "encrypted"), res
    assert sink.members == []


def test_missing_volume(src, scratch):
    paths = copy_fixture(["split_rar5.part1.rar", "split_rar5.part2.rar"], src)
    res, sink = run(paths, scratch_dir=scratch)
    assert res.status == "failed" and res.reason in (
        "missing_volume",
        "reader_error",
    ), res
    assert ("data/big.bin",) not in sink.by_chain()


def test_missing_volume_file(src, scratch):
    paths = copy_fixture(["split_rar5.part1.rar"], src) + [src / "split_rar5.part2.rar"]
    res, _ = run(paths, scratch_dir=scratch)
    assert (res.status, res.reason) == ("failed", "missing_volume")


def test_not_an_archive(src, scratch):
    p = src / "fake.zip"
    p.write_text("<html>404</html>")
    res, _ = run([p], scratch_dir=scratch)
    assert (res.status, res.reason) == ("failed", "unsupported_format"), res


# -------------------------------------------------------------------------- nested detection


def test_nested_archive_detected_by_magic(src, scratch):
    seven = (FIXTURES / "basic_lzma2.7z").read_bytes()
    p = zip_files(src / "outer.zip", {"payload.bin": seven, "x.txt": b"x"})
    res, sink = run([p], scratch_dir=scratch)
    assert res.status == "done"
    assert sink.by_chain()[("payload.bin",)][3] == "archive"
    assert sink.nested_results[("payload.bin",)].status == "done"
    assert sink.nested_results[("payload.bin",)].members == 6


def test_nested_single_file_gzip(src, scratch):
    gz = (FIXTURES / "model.stl.gz").read_bytes()
    p = zip_files(src / "outer.zip", {"parts/model.stl.gz": gz})
    res, sink = run([p], scratch_dir=scratch)
    assert res.status == "done"
    m = sink.by_chain()[("parts/model.stl.gz", "model.stl")]
    assert m[3] == "mesh" and m[4] == 12 and m[5] == 2
    assert sink.nested_results[("parts/model.stl.gz",)].reader == "stream"


def test_duplicate_member_names_get_unique_chains(src, scratch):
    p = src / "dup.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("a.txt", b"one")
        with pytest.warns(UserWarning):
            z.writestr("a.txt", b"two")
    res, sink = run([p], scratch_dir=scratch)
    assert res.status == "done"
    assert set(sink.by_chain()) == {("a.txt",), ("a.txt//dup1",)}


@needs_7zz
def test_deflate64_uses_7zz_fallback(src, scratch):
    res, _ = run(copy_fixture(["deflate64.zip"], src), scratch_dir=scratch)
    assert (res.status, res.reader) == ("done", "7zz") and res.members == 6


@needs_7zz
def test_7zz_fallback_never_materialises_links(src, scratch, tmp_path, monkeypatch):
    """Symlink-dir escape (entry ``d`` -> outside, then ``d/pwned.txt``) through the 7zz path."""
    from forge.engine import archive
    from forge.engine.caps import LocalFailure

    outside = tmp_path / "outside"
    outside.mkdir()
    p = src / "escape.zip"
    with zipfile.ZipFile(p, "w") as z:
        link = zipfile.ZipInfo("d")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        z.writestr(link, str(outside))
        z.writestr("d/pwned.txt", b"pwned")
        z.writestr("../up.txt", b"pwned")
        z.writestr("ok.txt", b"fine")

    def broken(*_a, **_k):
        raise LocalFailure("reader_error", "forced for test")

    monkeypatch.setattr(archive, "read_libarchive", broken)
    res, sink = run([p], scratch_dir=scratch, isolate=False)
    assert (res.status, res.reader) == ("done", "7zz"), res
    assert list(outside.iterdir()) == []
    assert not (tmp_path / "up.txt").exists() and not (src / "up.txt").exists()
    assert {c[-1]: r for c, r in sink.refusals} == {"d": "symlink", "../up.txt": "parent_traversal"}
    assert set(sink.by_chain()) == {("d/pwned.txt",), ("ok.txt",)}  # a real dir on scratch


# ------------------------------------------------------------------ kill-switch, OOM, sink, RSS


def test_kill_switch_stuck_reader(src, scratch, monkeypatch):
    monkeypatch.setenv("FORGE_ENGINE_TEST_STALL_SECONDS", "60")
    paths = copy_fixture(["basic.zip"], src)
    t0 = time.monotonic()
    res, sink = run(
        paths, caps=Caps(wall_seconds=1, kill_grace_seconds=1), scratch_dir=scratch
    )
    assert (res.status, res.reason) == ("failed", "timeout"), res
    assert time.monotonic() - t0 < 10
    assert sink.members == []


def test_address_space_cap_is_typed_oom(src, scratch):
    paths = copy_fixture(["basic_lzma2.7z"], src)
    res, _ = run(paths, caps=Caps(memory_bytes=48 << 20), scratch_dir=scratch)
    assert (res.status, res.reason) == ("failed", "oom"), res


def test_sink_exception_propagates_and_cleans_up(src, scratch):
    from .conftest import RecordingSink

    class Boom(RecordingSink):
        def member(self, *a):
            raise RuntimeError("db down")

    ref = ContainerRef("archive", tuple(copy_fixture(["basic.zip"], src)), "basic.zip")
    with pytest.raises(RuntimeError, match="db down"):
        process(ref, Boom(), Caps(), scratch)


def test_scratch_guard(src, tmp_path):
    paths = copy_fixture(["basic.zip"], src)
    ref = ContainerRef("archive", tuple(paths), "basic.zip")
    inside = src / "scratch"
    inside.mkdir()
    with pytest.raises(ValueError, match="inside the source tree"):
        process(ref, None, Caps(), inside)
    with pytest.raises(ValueError, match="does not exist"):
        process(ref, None, Caps(), tmp_path / "nope")


def test_peak_rss_largest_fixture(src, scratch):
    """AC5: the largest fixture (192 MiB member + nested archive) stays far below 2 GiB RSS."""
    p = src / "large.zip"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_STORED) as z:
        with z.open("big/random.bin", "w", force_zip64=True) as f:
            for _ in range(192):
                f.write(os.urandom(1 << 20))
        z.write(FIXTURES / "basic_rar5_solid.rar", "nested/basic.rar")
    res, sink = run([p], scratch_dir=scratch)
    assert res.status == "done", res
    assert sink.by_chain()[("big/random.bin",)][2] == 192 << 20
    child_peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    print(
        f"reader peak RSS {res.peak_rss_kb} KiB; RUSAGE_CHILDREN max {child_peak} KiB"
    )
    assert res.peak_rss_kb < 256 * 1024
    assert child_peak < WORKER_MEMORY_LIMIT_KB
