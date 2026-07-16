"""
List Google Drive folders (via gdown internals) and download only files
whose basename is not already present under the local etsy folder.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import gdown
from gdown.download_folder import download_and_parse_google_drive_link

LOCAL = Path(r"W:\3D-Prints-Unorg\etsy")
STAGING = Path(r"W:\3D-Prints-Unorg\etsy\_from_drive")
FOLDER_URLS = [
    "https://drive.google.com/drive/folders/1YKZjC4nQinccemYrX7nMVgtbaZHqNVrz?usp=sharing",
    "https://drive.google.com/drive/folders/1pX5bCG4lqnrKC7-f9iqeUikrgswtF-TC?usp=sharing",
    "https://drive.google.com/drive/folders/1s12saG5zKZErIqjlhO4lCV7Q2z9f16fw?usp=sharing",
]
# shortcuts found in etsy folder
EXTRA_FILE_IDS = [
    "1xZCzdei3558C-Nw4LL-gSGV2TOi4TwEY",  # 150.gshortcut
    "1KjNpWz3dEorhaJ1K6cXqsrYg6nukYKTp",  # 75.gshortcut
]


def local_basenames() -> set[str]:
    names = set()
    if not LOCAL.exists():
        return names
    for p in LOCAL.iterdir():
        if p.is_file():
            names.add(p.name.lower())
            names.add(p.stem.lower())
    return names


def walk_gdrive_file(node, acc: list):
    """Flatten gdown folder tree into (id, name, is_folder)."""
    # GoogleDriveFileToDownload-like object
    file_id = getattr(node, "id", None) or getattr(node, "id", None)
    name = getattr(node, "name", None) or getattr(node, "title", None)
    children = getattr(node, "children", None) or []
    is_folder = bool(children) or getattr(node, "type", "") == "application/vnd.google-apps.folder"
    if file_id and name:
        acc.append((file_id, name, is_folder, children))
    for ch in children or []:
        walk_gdrive_file(ch, acc)


def list_folder(url: str):
    print(f"\n=== Listing {url} ===", flush=True)
    try:
        # gdown 5.x / 6.x
        return_code, gdrive_file = download_and_parse_google_drive_link(
            gdown.download.sess if hasattr(gdown, "download") else None,
            url,
            quiet=False,
            remaining_ok=True,
        )
    except TypeError:
        # signature variants
        try:
            from gdown.download import get_session

            sess = get_session(use_cookies=True)
            return_code, gdrive_file = download_and_parse_google_drive_link(
                sess, url, quiet=False, remaining_ok=True
            )
        except Exception as e:
            print(f"list failed: {e}", flush=True)
            return []
    except Exception as e:
        print(f"list failed: {e}", flush=True)
        return []

    if gdrive_file is None:
        print("No gdrive_file returned", flush=True)
        return []
    acc = []
    walk_gdrive_file(gdrive_file, acc)
    print(f"nodes: {len(acc)}", flush=True)
    return acc


def main():
    do_download = "--download" in sys.argv
    local = local_basenames()
    print(f"Local basenames: {len(local)} under {LOCAL}")

    all_files = []
    for url in FOLDER_URLS:
        nodes = list_folder(url)
        for fid, name, is_folder, _ in nodes:
            if is_folder:
                continue
            all_files.append((fid, name, url))

    print(f"\nTotal remote files found: {len(all_files)}")
    missing = []
    present = []
    for fid, name, url in all_files:
        key = name.lower()
        stem = Path(name).stem.lower()
        if key in local or stem in local:
            present.append(name)
        else:
            missing.append((fid, name, url))

    print(f"Already local (name/stem match): {len(present)}")
    print(f"Missing: {len(missing)}")
    for fid, name, url in missing[:80]:
        print(f"  MISSING {name}  id={fid}")
    if len(missing) > 80:
        print(f"  ... +{len(missing)-80} more")

    if not do_download:
        print("\nDry list only. Re-run with --download to fetch missing into", STAGING)
        return

    STAGING.mkdir(parents=True, exist_ok=True)
    # also try shortcut file ids
    for fid in EXTRA_FILE_IDS:
        out = STAGING / f"shortcut_{fid}"
        print(f"Downloading shortcut {fid}...", flush=True)
        try:
            gdown.download(id=fid, output=str(out), quiet=False)
        except Exception as e:
            print(f"  fail {e}", flush=True)

    for fid, name, url in missing:
        # sanitize name
        safe = re.sub(r'[<>:"/\\|?*]', "_", name)
        out = STAGING / safe
        if out.exists() and out.stat().st_size > 0:
            print(f"skip exists {safe}", flush=True)
            continue
        print(f"Downloading {safe} ({fid})...", flush=True)
        try:
            gdown.download(id=fid, output=str(out), quiet=False)
            # move to etsy root if download ok
            if out.exists() and out.stat().st_size > 0:
                dest = LOCAL / safe
                if not dest.exists():
                    out.replace(dest)
                    print(f"  -> {dest}", flush=True)
        except Exception as e:
            print(f"  fail {e}", flush=True)


if __name__ == "__main__":
    main()
