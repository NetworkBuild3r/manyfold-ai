"""
Download only files missing from W:\\3D-Prints-Unorg\\etsy from the Google Drive
figure-archive folders (not the random utility STL dump folder).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import gdown

LOCAL = Path(r"W:\3D-Prints-Unorg\etsy")
# Figure / NSFW archive folders from 3dprint-Archive.pdf (skip the huge utility dump)
FOLDER_IDS = [
    # NSFW-style figure packs (matched Abe3D / Nomnom / etc. in listing)
    "1pX5bCG4lqnrKC7-f9iqeUikrgswtF-TC",
    "1s12saG5zKZErIqjlhO4lCV7Q2z9f16fw",
]
# Optional: utility dump — do NOT auto-download into etsy
# "1YKZjC4nQinccemYrX7nMVgtbaZHqNVrz"


def normalize(name: str) -> str:
    n = name.lower().strip()
    n = re.sub(r"\s+", " ", n)
    n = n.replace("+", " ")
    # strip trailing spaces before extension
    stem = Path(n).stem.strip()
    ext = Path(n).suffix.lower()
    return stem + ext


def local_keys() -> set[str]:
    keys: set[str] = set()
    for p in LOCAL.iterdir():
        if not p.is_file():
            continue
        keys.add(p.name.lower())
        keys.add(normalize(p.name))
        keys.add(Path(p.name).stem.lower().strip())
    return keys


def is_present(name: str, keys: set[str]) -> bool:
    if name.lower() in keys:
        return True
    if normalize(name) in keys:
        return True
    stem = Path(name).stem.lower().strip()
    if stem in keys:
        return True
    # fuzzy: any local stem contained in remote or vice versa (len>12)
    if len(stem) > 12:
        for k in keys:
            if len(k) > 12 and (stem in k or k in stem):
                return True
    return False


def main() -> None:
    do_dl = "--download" in sys.argv
    keys = local_keys()
    print(f"Local files: {sum(1 for p in LOCAL.iterdir() if p.is_file())}", flush=True)

    missing: list[tuple[str, str]] = []
    present = 0
    for fid in FOLDER_IDS:
        url = f"https://drive.google.com/drive/folders/{fid}"
        print(f"\n=== Listing {fid} ===", flush=True)
        try:
            files = gdown.download_folder(url=url, skip_download=True, quiet=False, resume=True)
        except Exception as e:
            print(f"LIST FAIL: {e}", flush=True)
            continue
        if not files:
            print("empty/none", flush=True)
            continue
        print(f"remote files: {len(files)}", flush=True)
        for f in files:
            name = Path(f.path).name if getattr(f, "path", None) else str(f)
            fid_file = getattr(f, "id", None)
            if is_present(name, keys):
                present += 1
            else:
                missing.append((fid_file, name))

    print(f"\nPresent (matched): {present}")
    print(f"Missing: {len(missing)}")
    for fid, name in missing:
        print(f"  MISSING {name}  id={fid}")

    if not do_dl:
        print("\nDry run. Pass --download to fetch missing into etsy.")
        return

    print("\n=== Downloading missing ===", flush=True)
    ok = 0
    fail = 0
    for fid, name in missing:
        if not fid:
            continue
        safe = re.sub(r'[<>:"/\\|?*]', "_", name).strip()
        dest = LOCAL / safe
        if dest.exists() and dest.stat().st_size > 0:
            print(f"skip exists {safe}", flush=True)
            continue
        print(f"GET {safe} ...", flush=True)
        try:
            out = gdown.download(id=fid, output=str(dest), quiet=False)
            if out and Path(out).exists() and Path(out).stat().st_size > 0:
                ok += 1
                print(f"  OK {Path(out).stat().st_size} bytes", flush=True)
            else:
                fail += 1
                print("  FAIL empty", flush=True)
        except Exception as e:
            fail += 1
            print(f"  FAIL {e}", flush=True)

    print(f"\nDone. ok={ok} fail={fail}")
    print(f"Etsy file count now: {sum(1 for p in LOCAL.iterdir() if p.is_file())}")


if __name__ == "__main__":
    main()
