"""List public Google Drive folder titles and compare to local etsy folder."""
import re
import urllib.request
from pathlib import Path

FOLDER_IDS = [
    ("NSFW-or-archive-1", "1YKZjC4nQinccemYrX7nMVgtbaZHqNVrz"),
    ("NSFW-or-archive-2", "1pX5bCG4lqnrKC7-f9iqeUikrgswtF-TC"),
    ("NSFW-or-archive-3", "1s12saG5zKZErIqjlhO4lCV7Q2z9f16fw"),
]

LOCAL = Path(r"W:\3D-Prints-Unorg\etsy")


def list_drive_folder(fid: str) -> tuple[set[str], str]:
    url = f"https://drive.google.com/drive/folders/{fid}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=45).read()
    html = raw.decode("utf-8", "replace")
    names: set[str] = set()
    for m in re.finditer(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', html):
        t = bytes(m.group(1), "utf-8").decode("unicode_escape", "replace")
        if t and t.lower() not in {"google drive", "drive", "shared with me", "my drive"}:
            names.add(t)
    # gapi encoded
    for m in re.finditer(r"\\x22title\\x22:\\x22([^\\]+)\\x22", html):
        names.add(m.group(1))
    status = "ok"
    if "Sign in" in html and len(names) < 3:
        status = "maybe-login-or-sparse"
    return names, status


def main() -> None:
    local_names = {p.name for p in LOCAL.iterdir() if p.is_file()}
    local_stems = {Path(n).stem.lower() for n in local_names}
    print(f"Local files: {len(local_names)} in {LOCAL}")

    all_remote: set[str] = set()
    for label, fid in FOLDER_IDS:
        try:
            names, status = list_drive_folder(fid)
        except Exception as e:
            print(f"=== {label} {fid} ERROR {e}")
            continue
        print(f"=== {label} {fid} status={status} count={len(names)}")
        for n in sorted(names)[:30]:
            print(f"  {n}")
        if len(names) > 30:
            print(f"  ... +{len(names) - 30} more")
        all_remote |= names

    print(f"\nTotal unique remote titles (HTML scrape): {len(all_remote)}")
    missing = []
    for n in sorted(all_remote):
        if n in local_names:
            continue
        stem = Path(n).stem.lower()
        # fuzzy: local has same stem
        if stem in local_stems:
            continue
        # local contains remote stem or vice versa
        if any(stem in ls or ls in stem for ls in local_stems if len(stem) > 8):
            continue
        missing.append(n)

    print(f"Possibly missing locally: {len(missing)}")
    for n in missing[:50]:
        print(f"  MISSING? {n}")
    if len(missing) > 50:
        print(f"  ... +{len(missing) - 50} more")


if __name__ == "__main__":
    main()
