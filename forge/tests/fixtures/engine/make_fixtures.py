#!/usr/bin/env python3
"""Regenerate the committed engine golden fixtures (needs ``rar`` 6.x and ``7zz``).

    RAR=/path/to/rar624/rar SEVENZIP=/path/to/7zz python make_fixtures.py

RAR 6.24 is used because RAR >= 7.0 can no longer write RAR4 (``-ma4``). Expected member
hashes in ``manifest.json`` are computed from the payload bytes written here, never from an
extraction, so the tests compare the engine against ground truth. Every archive is < 200 KB.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import shutil
import struct
import subprocess
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAR = os.environ.get("RAR", "rar")
SEVENZIP = os.environ.get("SEVENZIP", "7zz")


def binary_stl(n: int, seed: int) -> bytes:
    rnd = random.Random(seed)
    out = bytearray(b"solid binary-but-says-solid".ljust(80, b" "))
    out += struct.pack("<I", n)
    for _ in range(n):
        out += struct.pack("<12fH", *(rnd.uniform(-10, 10) for _ in range(12)), 0)
    return bytes(out)


def ascii_stl(n: int) -> bytes:
    lines = ["solid cube"]
    for i in range(n):
        lines += [
            f"  facet normal 0 0 {i % 2}",
            "    outer loop",
            f"      vertex {i} 0 0",
            f"      vertex 0 {i} 0",
            f"      vertex 0 0 {i}",
            "    endloop",
            "  endfacet",
        ]
    lines.append("endsolid cube")
    return ("\n".join(lines) + "\n").encode()


def payload_basic() -> dict[str, bytes]:
    rnd = random.Random(1)
    return {
        "models/cube_binary.stl": binary_stl(12, 2),
        "models/cube_ascii.stl": ascii_stl(12),
        "images/preview.png": b"\x89PNG\r\n\x1a\n" + rnd.randbytes(3000),
        "readme.txt": b"My AI Fitness? No: Library Forge golden fixture.\n" * 20,
        "empty.txt": b"",
        "data/random.bin": rnd.randbytes(20000),
    }


def write_tree(root: Path, files: dict[str, bytes]) -> None:
    for name, data in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def run(*argv, cwd: Path) -> None:
    subprocess.run([str(a) for a in argv], cwd=cwd, check=True, stdout=subprocess.DEVNULL)


def rar(out: Path, src: Path, *flags: str) -> None:
    out.unlink(missing_ok=True)
    run(RAR, "a", "-idq", "-ep1", "-r", "-m3", *flags, out, ".", cwd=src)


def sevenzip(out: Path, src: Path, *flags: str) -> None:
    out.unlink(missing_ok=True)
    run(SEVENZIP, "a", "-bd", *flags, out, ".", cwd=src)


def zip_dir(out: Path, files: dict[str, bytes], method=zipfile.ZIP_DEFLATED) -> bytes:
    with zipfile.ZipFile(out, "w", method) as z:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 2, 0, 0, 0))
            info.compress_type = method
            z.writestr(info, data)
    return out.read_bytes()


def entries(files: dict[str, bytes], prefix: tuple[str, ...] = (), depth: int = 1) -> list[dict]:
    out = []
    for name, data in files.items():
        tri = None
        if name.endswith(".stl"):
            tri = 12
        out.append(
            {
                "chain": [*prefix, name],
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "triangles": tri,
                "depth": depth,
            }
        )
    return out


def main() -> None:
    manifest: dict[str, dict] = {}
    basic = payload_basic()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        src = tmp / "basic"
        write_tree(src, basic)

        zip_dir(HERE / "basic.zip", basic)
        manifest["basic.zip"] = {
            "paths": ["basic.zip"],
            "format": "zip",
            "members": entries(basic),
        }

        rar(HERE / "basic_rar4.rar", src, "-ma4")
        manifest["basic_rar4.rar"] = {
            "paths": ["basic_rar4.rar"],
            "format": "rar4",
            "members": entries(basic),
        }

        rar(HERE / "basic_rar5_solid.rar", src, "-ma5", "-s")
        manifest["basic_rar5_solid.rar"] = {
            "paths": ["basic_rar5_solid.rar"],
            "format": "rar5",
            "members": entries(basic),
        }

        sevenzip(HERE / "basic_lzma2.7z", src, "-t7z", "-m0=lzma2", "-mx=9", "-ms=on")
        manifest["basic_lzma2.7z"] = {
            "paths": ["basic_lzma2.7z"],
            "format": "7z",
            "members": entries(basic),
        }

        # Deflate64 zip: libarchive cannot decode it, so this exercises the 7zz fallback.
        sevenzip(HERE / "deflate64.zip", src, "-tzip", "-mm=Deflate64")
        manifest["deflate64.zip"] = {
            "paths": ["deflate64.zip"],
            "format": "zip",
            "reader": "7zz",
            "members": entries(basic),
        }

        # Multi-volume sets (incompressible payload so the set really spans 3 volumes).
        big = dict(basic)
        big["data/big.bin"] = random.Random(7).randbytes(110_000)
        bsrc = tmp / "big"
        write_tree(bsrc, big)
        for f in HERE.glob("split_rar5.part*.rar"):
            f.unlink()
        rar(HERE / "split_rar5.rar", bsrc, "-ma5", "-v50k")
        vols = sorted(p.name for p in HERE.glob("split_rar5.part*.rar"))
        assert len(vols) == 3, vols
        manifest["split_rar5"] = {
            "paths": vols,
            "format": "rar5",
            "members": entries(big),
        }

        for f in [*HERE.glob("split_rar4.r[0-9][0-9]"), HERE / "split_rar4.rar"]:
            f.unlink(missing_ok=True)
        rar(HERE / "split_rar4.rar", bsrc, "-ma4", "-v50k", "-vn")
        vols4 = [
            "split_rar4.rar",
            *sorted(p.name for p in HERE.glob("split_rar4.r[0-9][0-9]")),
        ]
        assert len(vols4) == 3, vols4
        manifest["split_rar4"] = {
            "paths": vols4,
            "format": "rar4",
            "members": entries(big),
        }

        for f in HERE.glob("split_raw.7z.[0-9][0-9][0-9]"):
            f.unlink()
        sevenzip(HERE / "split_raw.7z", bsrc, "-t7z", "-m0=copy", "-v50k")
        raw = sorted(p.name for p in HERE.glob("split_raw.7z.[0-9][0-9][0-9]"))
        assert len(raw) == 3, raw
        manifest["split_raw.7z"] = {
            "paths": raw,
            "format": "7z",
            "members": entries(big),
        }

        # zip-in-rar (depth 2)
        inner_zip = zip_dir(tmp / "inner.zip", basic)
        zr = tmp / "zr"
        write_tree(zr, {"inner.zip": inner_zip, "notes.txt": b"zip in rar\n"})
        rar(HERE / "zip_in_rar.rar", zr, "-ma5")
        top = {"inner.zip": inner_zip, "notes.txt": b"zip in rar\n"}
        manifest["zip_in_rar.rar"] = {
            "paths": ["zip_in_rar.rar"],
            "format": "rar5",
            "members": entries(top) + entries(basic, ("inner.zip",), 2),
            "nested": {"inner.zip": "done"},
        }

        # 7z-in-zip-in-rar (depth 3)
        leaf = {"model.stl": binary_stl(12, 3), "leaf.txt": b"depth three\n"}
        lsrc = tmp / "leaf"
        write_tree(lsrc, leaf)
        sevenzip(tmp / "inner.7z", lsrc, "-t7z", "-m0=lzma2")
        inner7z = (tmp / "inner.7z").read_bytes()
        mid = {"inner.7z": inner7z, "mid.txt": b"depth two\n"}
        mid_zip = zip_dir(tmp / "mid.zip", mid)
        top3 = {"mid.zip": mid_zip, "top.txt": b"depth one\n"}
        tsrc = tmp / "top3"
        write_tree(tsrc, top3)
        rar(HERE / "depth3.rar", tsrc, "-ma4")
        manifest["depth3.rar"] = {
            "paths": ["depth3.rar"],
            "format": "rar4",
            "members": entries(top3)
            + entries(mid, ("mid.zip",), 2)
            + entries(leaf, ("mid.zip", "inner.7z"), 3),
            "nested": {"mid.zip": "done", "mid.zip/inner.7z": "done"},
        }

        # Encrypted (7z with encrypted headers, zip with ZipCrypto)
        sevenzip(HERE / "encrypted.7z", lsrc, "-t7z", "-pforge", "-mhe=on")
        sevenzip(HERE / "encrypted.zip", lsrc, "-tzip", "-pforge")

        # single-file gzip (not tar)
        stl = binary_stl(12, 4)
        with (
            open(HERE / "model.stl.gz", "wb") as f,
            gzip.GzipFile(filename="", mode="wb", fileobj=f, mtime=0) as g,
        ):
            g.write(stl)
        manifest["model.stl.gz"] = {
            "paths": ["model.stl.gz"],
            "format": "gzip",
            "reader": "stream",
            "members": entries({"model.stl": stl}),
        }

    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    for p in sorted(HERE.iterdir()):
        if p.suffix != ".py" and p.name != "manifest.json":
            assert p.stat().st_size < 200_000, p
    print("ok", len(manifest), "fixtures")


if __name__ == "__main__":
    if shutil.which(RAR) is None and not Path(RAR).exists():
        raise SystemExit("set RAR to a rar 6.x binary")
    main()
