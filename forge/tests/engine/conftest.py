from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import struct
import subprocess
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "engine"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text())
REQUIRE_NATIVE = os.environ.get("FORGE_REQUIRE_NATIVE") == "1"


def _native_available() -> bool:
    try:
        import forge.engine._libarchive  # noqa: F401
    except (OSError, TypeError, AttributeError):
        return False
    return True


if not _native_available():
    if REQUIRE_NATIVE:
        raise RuntimeError("libarchive.so.13 is required (FORGE_REQUIRE_NATIVE=1)")
    pytest.skip("libarchive.so.13 not available", allow_module_level=True)


def sevenzip() -> str | None:
    from forge.engine.fallback import find_7zz

    return find_7zz()


needs_7zz = pytest.mark.skipif(
    sevenzip() is None and not REQUIRE_NATIVE,
    reason="7zz not installed (set FORGE_7ZZ)",
)


@dataclass
class RecordingSink:
    members: list[tuple] = field(default_factory=list)
    refusals: list[tuple] = field(default_factory=list)
    nested: list[tuple] = field(default_factory=list)
    nested_results: dict = field(default_factory=dict)
    events: list[str] = field(default_factory=list)

    def member(self, chain, sha256, size, kind, triangles, depth):
        self.members.append((chain, sha256, size, kind, triangles, depth))
        self.events.append("m:" + "/".join(chain))

    def refused(self, chain, reason):
        self.refusals.append((chain, reason))
        self.events.append("r:" + "/".join(chain))

    def nested_archive(self, chain, sha256, size):
        self.nested.append((chain, sha256, size))
        self.events.append("n:" + "/".join(chain))

    def nested_result(self, chain, result):
        self.nested_results[chain] = result
        self.events.append("nr:" + "/".join(chain))

    def by_chain(self) -> dict[tuple, tuple]:
        return {m[0]: m for m in self.members}


@pytest.fixture
def src(tmp_path: Path) -> Path:
    d = tmp_path / "src"
    d.mkdir()
    return d


@pytest.fixture
def scratch(tmp_path: Path) -> Path:
    d = tmp_path / "scratch"
    d.mkdir()
    yield d
    leftovers = list(d.iterdir())
    assert leftovers == [], f"scratch not cleaned: {leftovers}"


def copy_fixture(names: list[str], dest: Path) -> list[Path]:
    """Copy fixtures into ``dest`` and make them read-only (the engine must never write them)."""
    out = []
    for n in names:
        p = dest / n
        shutil.copyfile(FIXTURES / n, p)
        p.chmod(stat.S_IRUSR | stat.S_IRGRP)
        out.append(p)
    return out


def tree_snapshot(root: Path, skip: Path | None = None) -> dict[str, str]:
    snap = {}
    for p in sorted(root.rglob("*")):
        if skip is not None and (p == skip or skip in p.parents):
            continue
        if p.is_symlink():
            snap[str(p.relative_to(root))] = "link:" + os.readlink(p)
        elif p.is_file():
            snap[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
        else:
            snap[str(p.relative_to(root))] = "dir"
    return snap


def run(paths, caps=None, scratch_dir=None, isolate=True):
    from forge.engine import Caps, ContainerRef, process

    sink = RecordingSink()
    ref = ContainerRef("archive", tuple(Path(p) for p in paths), str(paths[0]))
    res = process(ref, sink, caps or Caps(), scratch_dir, isolate=isolate)
    return res, sink


def zeros_zip(path: Path, size: int = 1 << 30, name: str = "zeros.bin") -> Path:
    """A zip whose single deflated member is ``size`` zero bytes (~1 KB per MiB on disk).

    Built by repeating one full-flush deflate block, so a 1 GiB member costs milliseconds.
    """
    chunk = 1 << 20
    assert size % chunk == 0
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    zeros = b"\0" * chunk
    block = c.compress(zeros) + c.flush(zlib.Z_FULL_FLUSH)
    assert c.compress(zeros) + c.flush(zlib.Z_FULL_FLUSH) == block
    data = block * (size // chunk) + c.flush(zlib.Z_FINISH)
    crc = 0
    for _ in range(size // chunk):
        crc = zlib.crc32(zeros, crc)
    fname = name.encode()
    local = struct.pack(
        "<IHHHHHIIIHH", 0x04034B50, 20, 0, 8, 0, 0, crc, len(data), size, len(fname), 0
    )
    central = struct.pack(
        "<IHHHHHHIIIHHHHHII",
        0x02014B50,
        20,
        20,
        0,
        8,
        0,
        0,
        crc,
        len(data),
        size,
        len(fname),
        0,
        0,
        0,
        0,
        0,
        0,
    )
    cd_offset = len(local) + len(fname) + len(data)
    cd = central + fname
    eocd = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 1, 1, len(cd), cd_offset, 0)
    path.write_bytes(local + fname + data + cd + eocd)
    return path


def zip_files(path: Path, files: dict[str, bytes], method=zipfile.ZIP_DEFLATED) -> Path:
    with zipfile.ZipFile(path, "w", method) as z:
        for n, d in files.items():
            info = zipfile.ZipInfo(n, date_time=(2026, 10, 2, 0, 0, 0))
            info.compress_type = method
            z.writestr(info, d)
    return path


def reference_extract(
    paths: list[Path], out: Path, depth: int = 1, prefix: tuple = ()
) -> dict[tuple, str]:
    """Independent reference: 7zz extraction + sha256 of every file, recursing into archives."""
    from forge.engine.kinds import classify

    exe = sevenzip()
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [exe, "x", "-y", "-bd", f"-o{out}", "--", str(paths[0])],
        check=True,
        capture_output=True,
    )
    found = {}
    for p in sorted(out.rglob("*")):
        if not p.is_file() or p.is_symlink():
            continue
        rel = str(p.relative_to(out))
        chain = (*prefix, rel)
        found[chain] = hashlib.sha256(p.read_bytes()).hexdigest()
        if classify(rel, p.read_bytes()[:512]) == "archive" and depth < 3:
            found.update(
                reference_extract(
                    [p],
                    out.parent / (out.name + "_" + rel.replace("/", "_")),
                    depth + 1,
                    chain,
                )
            )
    return found
