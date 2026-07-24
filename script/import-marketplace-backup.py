#!/usr/bin/env python3
"""Import Cults3D / Gumroad backups into a Manyfold library tree.

Reads marketplace manifests + on-disk Creator/Model folders, writes
datapackage.json (and optional preview.jpg), then moves winners into:

  <dest>/Cults3D/<creator>/<model>/
  <dest>/Gumroad/<creator>/<model>/

Duplicates: never delete. Richer pack (bytes + file count + preview) wins;
loser goes to <unorg>/_duplicates-quarantine/<source>/...

Default is dry-run. Pass --apply to execute moves/writes/downloads.

Examples:
  # Dry-run both
  python3 script/import-marketplace-backup.py --source both

  # Pilot one creator
  python3 script/import-marketplace-backup.py --source gumroad --creator Abe3D --apply

  # Full cults then gumroad
  python3 script/import-marketplace-backup.py --source cults3d --apply
  python3 script/import-marketplace-backup.py --source gumroad --apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

DEFAULT_UNORG = Path("/mnt/backups/3D-Prints-Unorg")
DEFAULT_DEST = Path("/mnt/backups/3D-Prints")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".stl", ".obj", ".3mf", ".gcode", ".lys", ".lyt"}
SKIP_NAMES = {".ds_store", "thumbs.db", "desktop.ini", "@eadir", "#recycle"}


def norm_name(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s.casefold()


def safe_slug(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "unnamed"


def is_preview_name(name: str) -> bool:
    stem = Path(name).stem.casefold()
    return stem in {"preview", "cover", "thumb", "thumbnail"} or stem.startswith("preview")


@dataclass
class PackScore:
    bytes_total: int = 0
    file_count: int = 0
    has_preview: bool = False

    @property
    def score(self) -> tuple:
        # Higher is better. Raw payload size first; file count; small preview flag.
        # Do NOT inflate bytes with a large preview bonus — that flipped Gumroad
        # multi-zip packs against Cults single-zip+preview downloads.
        return (self.bytes_total, self.file_count, int(self.has_preview))


@dataclass
class ModelPack:
    source_tag: str  # Cults3D | Gumroad
    creator: str
    title: str
    path: Path
    meta: dict[str, Any] = field(default_factory=dict)
    score: PackScore = field(default_factory=PackScore)

    @property
    def dedupe_key(self) -> str:
        return f"{self.source_tag.casefold()}|{norm_name(self.creator)}|{norm_name(self.title)}"


@dataclass
class PlanAction:
    action: str
    source: Optional[str] = None
    creator: Optional[str] = None
    title: Optional[str] = None
    src: Optional[str] = None
    dest: Optional[str] = None
    quarantine: Optional[str] = None
    reason: Optional[str] = None
    score_src: Optional[list] = None
    score_dest: Optional[list] = None


def score_directory(path: Path) -> PackScore:
    bytes_total = 0
    file_count = 0
    has_preview = False
    if not path.is_dir():
        return PackScore()
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d.casefold() not in SKIP_NAMES and not d.startswith(".")]
        for name in files:
            if name.casefold() in SKIP_NAMES or name.startswith("."):
                continue
            if name.casefold() in {"datapackage.json", "metadata.json"}:
                continue
            fp = Path(root) / name
            try:
                size = fp.stat().st_size
            except OSError:
                continue
            ext = fp.suffix.casefold()
            if ext in IMAGE_EXTS or ext in ARCHIVE_EXTS or True:
                bytes_total += size
                file_count += 1
            if ext in IMAGE_EXTS and (is_preview_name(name) or True):
                # Any image counts as preview presence for scoring.
                has_preview = True
    return PackScore(bytes_total=bytes_total, file_count=file_count, has_preview=has_preview)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def index_manifest_cults(manifest: dict) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for item in manifest.get("items") or []:
        creator = (item.get("creator") or "").strip()
        name = (item.get("name") or "").strip()
        if not creator or not name:
            continue
        out[(norm_name(creator), norm_name(name))] = item
    return out


def index_manifest_gumroad(manifest: dict) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for item in manifest.get("items") or []:
        creator = (item.get("creator") or item.get("artist") or "").strip()
        name = (item.get("name") or "").strip()
        if not creator or not name:
            continue
        out[(norm_name(creator), norm_name(name))] = item
    return out


def discover_model_dirs(tree_root: Path, creator_filter: Optional[str]) -> list[tuple[str, str, Path]]:
    """Return (creator, title, path) for each model folder under tree_root/<creator>/<model>."""
    found: list[tuple[str, str, Path]] = []
    if not tree_root.is_dir():
        return found
    for creator_dir in sorted(tree_root.iterdir()):
        if not creator_dir.is_dir() or creator_dir.name.startswith("."):
            continue
        if creator_filter and creator_dir.name.casefold() != creator_filter.casefold():
            continue
        for model_dir in sorted(creator_dir.iterdir()):
            if not model_dir.is_dir() or model_dir.name.startswith("."):
                continue
            found.append((creator_dir.name, model_dir.name, model_dir))
    return found


def merge_meta(folder_meta: dict, manifest_item: Optional[dict], source_tag: str) -> dict:
    meta = dict(folder_meta or {})
    if manifest_item:
        for k, v in manifest_item.items():
            if v is not None and (k not in meta or meta.get(k) in (None, "", [])):
                meta[k] = v
    meta.setdefault("source", source_tag.casefold())
    return meta


def list_payload_files(model_dir: Path) -> list[Path]:
    files: list[Path] = []
    for p in sorted(model_dir.iterdir()):
        if not p.is_file():
            continue
        if p.name.casefold() in SKIP_NAMES or p.name.startswith("."):
            continue
        if p.name.casefold() in {"datapackage.json", "metadata.json"}:
            continue
        files.append(p)
    return files


def guess_mediatype(path: Path) -> str:
    mt, _ = mimetypes.guess_type(str(path))
    if mt:
        return mt
    ext = path.suffix.casefold()
    return {
        ".stl": "model/stl",
        ".obj": "model/obj",
        ".3mf": "model/3mf",
        ".zip": "application/zip",
        ".rar": "application/vnd.rar",
        ".7z": "application/x-7z-compressed",
    }.get(ext, "application/octet-stream")


def find_existing_preview(model_dir: Path) -> Optional[str]:
    for p in list_payload_files(model_dir):
        if p.suffix.casefold() in IMAGE_EXTS and is_preview_name(p.name):
            return p.name
    for p in list_payload_files(model_dir):
        if p.suffix.casefold() in IMAGE_EXTS:
            return p.name
    return None


def build_datapackage(
    title: str,
    creator: str,
    source_tag: str,
    model_dir: Path,
    meta: dict,
) -> dict:
    keywords = [source_tag.casefold(), safe_slug(creator).replace("-", " ")]
    # Light keyword tokens from title (keep short words out)
    for tok in re.split(r"[\W_+-]+", title):
        if len(tok) > 2:
            keywords.append(tok.casefold())
    # Dedupe preserving order
    seen = set()
    kw: list[str] = []
    for k in keywords:
        if k not in seen:
            seen.add(k)
            kw.append(k)

    preview = find_existing_preview(model_dir)
    resources = []
    for p in list_payload_files(model_dir):
        resources.append(
            {
                "name": safe_slug(p.stem),
                "path": p.name,
                "mediatype": guess_mediatype(p),
                "up": "+z",
                "presupported": "support" in p.name.casefold() or "presupported" in p.name.casefold(),
            }
        )

    contributor: dict[str, Any] = {
        "title": creator,
        "roles": ["creator"],
    }
    profile = meta.get("profile_url") or meta.get("path")
    if profile:
        contributor["path"] = profile

    homepage = (
        meta.get("downloadUrl")
        or meta.get("download_page_url")
        or meta.get("homepage")
        or profile
    )
    links = []
    if homepage:
        links.append({"path": homepage})
    if profile and profile != homepage:
        links.append({"path": profile})

    caption = f"{source_tag} model by {creator}."
    description = meta.get("description") or caption

    pkg = {
        "$schema": "https://manyfold.app/profiles/0.0/datapackage.json",
        "name": safe_slug(title),
        "title": title,
        "keywords": kw[:40],
        "sensitive": False,
        "resources": resources,
        "collections": [],
        "links": links,
        "caption": caption,
        "description": description,
        "contributors": [contributor],
    }
    if preview:
        pkg["image"] = preview
    if homepage:
        pkg["homepage"] = homepage
    return pkg


def download_preview(url: str, dest: Path, timeout: int = 60) -> bool:
    # Prefer original from Cults CDN when present after ()/
    raw = url
    if "()/" in url:
        raw = url.split("()/", 1)[-1]
    try:
        req = urllib.request.Request(
            raw,
            headers={"User-Agent": "manyfold-import-marketplace-backup/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        if not data or len(data) < 100:
            return False
        dest.write_bytes(data)
        return True
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        print(f"  ! preview download failed: {exc}", file=sys.stderr)
        return False


def ensure_unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    i = 2
    while True:
        alt = path.with_name(f"{path.name} ({i})")
        if not alt.exists():
            return alt
        i += 1


def move_path(src: Path, dest: Path, apply: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not apply:
        return
    if dest.exists():
        raise FileExistsError(f"destination exists: {dest}")
    try:
        os.rename(src, dest)
    except OSError:
        shutil.move(str(src), str(dest))


def write_datapackage(model_dir: Path, pkg: dict, apply: bool) -> None:
    path = model_dir / "datapackage.json"
    text = json.dumps(pkg, indent=2, ensure_ascii=False) + "\n"
    if apply:
        path.write_text(text, encoding="utf-8")


def build_packs_for_source(
    source: str,
    backup_root: Path,
    creator_filter: Optional[str],
) -> tuple[list[ModelPack], dict[tuple[str, str], dict], list[str]]:
    """source: cults3d | gumroad"""
    unmatched: list[str] = []
    manifest_path = backup_root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing manifest: {manifest_path}")

    if source == "cults3d":
        source_tag = "Cults3D"
        tree = backup_root / "Cults3D"
        manifest = load_json(manifest_path)
        index = index_manifest_cults(manifest)
        model_dirs = discover_model_dirs(tree, creator_filter)
    elif source == "gumroad":
        source_tag = "Gumroad"
        tree = backup_root / "Gumroad"
        manifest = load_json(manifest_path)
        index = index_manifest_gumroad(manifest)
        model_dirs = discover_model_dirs(tree, creator_filter)
    else:
        raise ValueError(source)

    packs: list[ModelPack] = []
    seen_keys: set[tuple[str, str]] = set()
    for creator, title, path in model_dirs:
        folder_meta: dict = {}
        meta_file = path / "metadata.json"
        if meta_file.is_file():
            try:
                folder_meta = load_json(meta_file)
            except json.JSONDecodeError:
                folder_meta = {}
        key = (norm_name(creator), norm_name(title))
        # Gumroad folder title may be product_name while manifest uses longer name
        item = index.get(key)
        if not item and folder_meta.get("product_name"):
            item = index.get((norm_name(creator), norm_name(folder_meta["product_name"])))
        if not item:
            # try match by product_id
            pid = folder_meta.get("product_id")
            if pid:
                for it in index.values():
                    if it.get("product_id") == pid:
                        item = it
                        break
        meta = merge_meta(folder_meta, item, source_tag)
        if item:
            seen_keys.add(key)
            # Prefer manifest display name when folder name is short product title
            if item.get("name") and norm_name(item["name"]) == norm_name(title):
                title = item["name"].strip()
        pack = ModelPack(
            source_tag=source_tag,
            creator=creator,
            title=title,
            path=path,
            meta=meta,
            score=score_directory(path),
        )
        packs.append(pack)

    for (c, n), item in index.items():
        if creator_filter and c != norm_name(creator_filter):
            continue
        if (c, n) not in seen_keys and (c, n) not in {(norm_name(p.creator), norm_name(p.title)) for p in packs}:
            unmatched.append(f"{item.get('creator')}/{item.get('name')}")

    return packs, index, unmatched


def plan_cross_source_dedupe(dest_root: Path, quarantine_root: Path) -> list[PlanAction]:
    """When the same creator/title exists under both Cults3D and Gumroad, keep the richer pack."""
    actions: list[PlanAction] = []
    cults = dest_root / "Cults3D"
    gumroad = dest_root / "Gumroad"
    if not cults.is_dir() or not gumroad.is_dir():
        return actions

    gum_creators = {p.name.casefold(): p for p in gumroad.iterdir() if p.is_dir()}
    for cults_creator in sorted(cults.iterdir()):
        if not cults_creator.is_dir():
            continue
        gum_creator = gum_creators.get(cults_creator.name.casefold())
        if not gum_creator:
            continue
        gum_models = {norm_name(p.name): p for p in gum_creator.iterdir() if p.is_dir()}
        for cults_model in sorted(cults_creator.iterdir()):
            if not cults_model.is_dir():
                continue
            gum_model = gum_models.get(norm_name(cults_model.name))
            if not gum_model:
                continue
            cs = score_directory(cults_model)
            gs = score_directory(gum_model)
            # Prefer Gumroad on tie / near-tie (native marketplace pack usually richer).
            if gs.bytes_total >= int(cs.bytes_total * 0.95) and gs.file_count >= cs.file_count:
                winner, loser, win_tag, lose_tag = gum_model, cults_model, "Gumroad", "Cults3D"
            elif cs.score > gs.score:
                winner, loser, win_tag, lose_tag = cults_model, gum_model, "Cults3D", "Gumroad"
            else:
                winner, loser, win_tag, lose_tag = gum_model, cults_model, "Gumroad", "Cults3D"
            q = quarantine_root / "cross-source" / lose_tag.casefold() / cults_creator.name / loser.name
            q = ensure_unique_path(q) if q.exists() else q
            actions.append(
                PlanAction(
                    action="quarantine_loser",
                    source=f"{lose_tag}->{win_tag}",
                    creator=cults_creator.name,
                    title=loser.name,
                    src=str(loser),
                    dest=str(winner),
                    quarantine=str(q),
                    reason="cross_source_duplicate_keep_richer",
                    score_src=list(score_directory(loser).score),
                    score_dest=list(score_directory(winner).score),
                )
            )
    return actions


def plan_import(
    packs: list[ModelPack],
    dest_root: Path,
    quarantine_root: Path,
) -> list[PlanAction]:
    actions: list[PlanAction] = []
    for pack in packs:
        dest = dest_root / pack.source_tag / pack.creator / pack.title
        existing = dest if dest.is_dir() else None
        # Also check case-insensitive collision under creator
        if existing is None:
            creator_dir = dest_root / pack.source_tag / pack.creator
            if creator_dir.is_dir():
                for child in creator_dir.iterdir():
                    if child.is_dir() and norm_name(child.name) == norm_name(pack.title):
                        existing = child
                        dest = child
                        break

        if existing is None:
            actions.append(
                PlanAction(
                    action="move",
                    source=pack.source_tag,
                    creator=pack.creator,
                    title=pack.title,
                    src=str(pack.path),
                    dest=str(dest_root / pack.source_tag / pack.creator / pack.title),
                    reason="new",
                    score_src=list(pack.score.score),
                )
            )
            continue

        existing_score = score_directory(existing)
        if pack.score.score > existing_score.score:
            q = quarantine_root / pack.source_tag.casefold() / pack.creator / existing.name
            q = ensure_unique_path(q) if q.exists() else q
            actions.append(
                PlanAction(
                    action="replace_with_richer",
                    source=pack.source_tag,
                    creator=pack.creator,
                    title=pack.title,
                    src=str(pack.path),
                    dest=str(existing),
                    quarantine=str(q),
                    reason="backup_richer_than_library",
                    score_src=list(pack.score.score),
                    score_dest=list(existing_score.score),
                )
            )
        else:
            q = quarantine_root / pack.source_tag.casefold() / pack.creator / pack.path.name
            q = ensure_unique_path(q) if q.exists() else q
            actions.append(
                PlanAction(
                    action="quarantine_loser",
                    source=pack.source_tag,
                    creator=pack.creator,
                    title=pack.title,
                    src=str(pack.path),
                    dest=str(existing),
                    quarantine=str(q),
                    reason="library_equal_or_richer",
                    score_src=list(pack.score.score),
                    score_dest=list(existing_score.score),
                )
            )
    return actions


def maybe_fetch_preview(pack: ModelPack, apply: bool) -> bool:
    if find_existing_preview(pack.path):
        return False
    url = pack.meta.get("illustrationImageUrl")
    if not url and pack.meta.get("illustrations"):
        first = pack.meta["illustrations"][0]
        if isinstance(first, dict):
            url = first.get("imageUrl")
    if not url:
        return False
    dest = pack.path / "preview.jpg"
    if not apply:
        return True  # would download
    return download_preview(url, dest)


def execute_actions(
    packs_by_src: dict[str, ModelPack],
    actions: list[PlanAction],
    apply: bool,
    download_previews: bool,
) -> dict[str, int]:
    counts = {
        "move": 0,
        "replace_with_richer": 0,
        "quarantine_loser": 0,
        "datapackage": 0,
        "preview_download": 0,
        "errors": 0,
    }
    for act in actions:
        key = act.src or ""
        pack = packs_by_src.get(key)
        try:
            if pack and download_previews:
                if maybe_fetch_preview(pack, apply=apply):
                    counts["preview_download"] += 1
                    if apply:
                        pack.score = score_directory(pack.path)

            if pack:
                pkg = build_datapackage(pack.title, pack.creator, pack.source_tag, pack.path, pack.meta)
                # If we just added preview, refresh image field
                if apply:
                    preview = find_existing_preview(pack.path)
                    if preview:
                        pkg["image"] = preview
                write_datapackage(pack.path, pkg, apply=apply)
                counts["datapackage"] += 1

            if act.action == "move":
                assert act.src and act.dest
                move_path(Path(act.src), Path(act.dest), apply=apply)
                counts["move"] += 1
            elif act.action == "replace_with_richer":
                assert act.src and act.dest and act.quarantine
                # Move library copy to quarantine, then move backup into dest
                move_path(Path(act.dest), Path(act.quarantine), apply=apply)
                move_path(Path(act.src), Path(act.dest), apply=apply)
                counts["replace_with_richer"] += 1
            elif act.action == "quarantine_loser":
                assert act.src and act.quarantine
                move_path(Path(act.src), Path(act.quarantine), apply=apply)
                counts["quarantine_loser"] += 1
            else:
                print(f"unknown action {act.action}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 — keep going across models
            counts["errors"] += 1
            print(f"ERROR {act.action} {act.src}: {exc}", file=sys.stderr)
    return counts


def summarize(actions: list[PlanAction], unmatched: list[str]) -> None:
    from collections import Counter

    c = Counter(a.action for a in actions)
    print("\n=== Plan summary ===")
    for k, v in sorted(c.items()):
        print(f"  {k}: {v}")
    print(f"  unmatched_manifest_rows: {len(unmatched)}")
    if unmatched[:15]:
        print("  sample unmatched:")
        for u in unmatched[:15]:
            print(f"    - {u}")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=["cults3d", "gumroad", "both"], default="both")
    ap.add_argument("--unorg-root", type=Path, default=DEFAULT_UNORG)
    ap.add_argument("--dest-root", type=Path, default=DEFAULT_DEST)
    ap.add_argument("--creator", default=None, help="Only process this creator folder name")
    ap.add_argument("--apply", action="store_true", help="Execute moves/writes (default dry-run)")
    ap.add_argument("--no-preview-download", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="Max models per source (0 = all)")
    ap.add_argument(
        "--cross-dedupe-only",
        action="store_true",
        help="Only reconcile Cults3D vs Gumroad same creator/title under dest-root",
    )
    args = ap.parse_args(argv)

    unorg = args.unorg_root
    dest = args.dest_root
    quarantine = unorg / "_duplicates-quarantine"
    log_dir = unorg / ".manyfold-organize-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    log_path = log_dir / f"import-marketplace-{ts}.jsonl"

    if args.cross_dedupe_only:
        actions = plan_cross_source_dedupe(dest, quarantine)
        summarize(actions, [])
        with log_path.open("w", encoding="utf-8") as logf:
            for act in actions:
                logf.write(json.dumps(asdict(act), ensure_ascii=False) + "\n")
        print(f"Wrote plan log: {log_path}")
        if not args.apply:
            print("Dry-run only. Re-run with --cross-dedupe-only --apply to execute.")
            return 0
        counts = execute_actions({}, actions, apply=True, download_previews=False)
        print("=== Apply counts ===")
        for k, v in counts.items():
            print(f"  {k}: {v}")
        return 0 if counts["errors"] == 0 else 1

    sources = ["cults3d", "gumroad"] if args.source == "both" else [args.source]
    all_actions: list[PlanAction] = []
    all_unmatched: list[str] = []
    packs_by_src: dict[str, ModelPack] = {}

    for source in sources:
        backup_root = unorg / f"{source}-backup"
        if not backup_root.is_dir():
            print(f"SKIP missing {backup_root}", file=sys.stderr)
            continue
        packs, _index, unmatched = build_packs_for_source(source, backup_root, args.creator)
        if args.limit and args.limit > 0:
            packs = packs[: args.limit]
        print(f"[{source}] discovered {len(packs)} model folders, unmatched manifest {len(unmatched)}")
        for p in packs:
            packs_by_src[str(p.path)] = p
        actions = plan_import(packs, dest, quarantine)
        all_actions.extend(actions)
        all_unmatched.extend(unmatched)

    summarize(all_actions, all_unmatched)

    with log_path.open("w", encoding="utf-8") as logf:
        for act in all_actions:
            logf.write(json.dumps(asdict(act), ensure_ascii=False) + "\n")
        for u in all_unmatched:
            logf.write(json.dumps({"action": "unmatched_manifest", "ref": u}, ensure_ascii=False) + "\n")
    print(f"Wrote plan log: {log_path}")

    if not args.apply:
        print("Dry-run only. Re-run with --apply to execute.")
        return 0

    print("Applying…")
    counts = execute_actions(
        packs_by_src,
        all_actions,
        apply=True,
        download_previews=not args.no_preview_download,
    )
    print("=== Apply counts ===")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    return 0 if counts["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
