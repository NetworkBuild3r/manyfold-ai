# Archive-member recall scanner — zip central-directory listing + inverted index.
# Provenance: INIT-018/SPEC-004
#
# Matching lists ZipFile.infolist() only. ZipFile.read / member extract are
# forbidden on this path (zip-bomb / NFS). CRC+size+basename is recall, not apply
# identity — SPEC-005 consumes the inverted postings.
from __future__ import annotations

import json
import logging
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

from .config import CurateConfig
from .walk import ModelFolder, iter_model_folders

log = logging.getLogger(__name__)

# Mesh extensions preferred for STRONG overlap (ADR D-2 / D-4). Archives/images
# are listed when present but mesh-prefer filters drive apply admission later.
MESH_EXT = frozenset(
    {
        ".stl",
        ".obj",
        ".3mf",
        ".ply",
        ".gltf",
        ".glb",
        ".step",
        ".stp",
        ".fbx",
        ".lys",
        ".lyt",
        ".chitubox",
        ".ctb",
        ".sl1s",
        ".3dm",
    }
)

ZIP_EXT = frozenset({".zip"})

# Cap central-directory enumeration per archive (DoS / pathological zips).
DEFAULT_MAX_MEMBERS_PER_ARCHIVE = 5_000

# Artifact filename prefixes under .spark-curate/ (do not mix with organize plans).
ARCHIVE_INDEX_PREFIX = "archive-index"
ARCHIVE_INVERT_PREFIX = "archive-invert"

_JUNK_BASENAMES = frozenset(
    {
        ".ds_store",
        "thumbs.db",
        "desktop.ini",
        ".spotlight-v100",
        ".trashes",
    }
)


@dataclass(frozen=True)
class MemberSig:
    """One zip central-directory entry used for recall."""

    basename: str
    uncompressed_size: int
    crc32: int
    is_mesh: bool
    member_path: str

    @property
    def sig(self) -> str:
        return member_signature(self.basename, self.uncompressed_size, self.crc32)


@dataclass
class ZipListing:
    """Result of listing one outer zip (never extracts members)."""

    zip_path: str
    folder_rel: str
    members: list[MemberSig] = field(default_factory=list)
    mesh_count: int = 0
    truncated: bool = False
    max_members: int = DEFAULT_MAX_MEMBERS_PER_ARCHIVE
    skip_reason: str | None = None
    outer_size: int | None = None
    outer_mtime_ns: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "zip_path": self.zip_path,
            "folder_rel": self.folder_rel,
            "member_count": len(self.members),
            "mesh_count": self.mesh_count,
            "truncated": self.truncated,
            "max_members": self.max_members,
            "skip_reason": self.skip_reason,
            "outer_size": self.outer_size,
            "outer_mtime_ns": self.outer_mtime_ns,
            "members": [
                {
                    "basename": m.basename,
                    "uncompressed_size": m.uncompressed_size,
                    "crc32": m.crc32,
                    "is_mesh": m.is_mesh,
                    "member_path": m.member_path,
                    "sig": m.sig,
                }
                for m in self.members
            ],
        }


@dataclass
class ArchiveIndexResult:
    """
    Export surface for SPEC-005: inverted sig→folders plus per-zip listings.

    Postings are mesh-prefer by default (non-mesh still listed in ZipListing).
    """

    listings: list[ZipListing] = field(default_factory=list)
    # sig -> sorted unique folder_rel postings (mesh members only)
    inverted_mesh: dict[str, list[str]] = field(default_factory=dict)
    # sig -> sorted unique folder_rel (all non-junk members)
    inverted_all: dict[str, list[str]] = field(default_factory=dict)
    folders_scanned: int = 0
    zips_scanned: int = 0
    zips_skipped: int = 0
    zips_truncated: int = 0
    index_jsonl_path: str | None = None
    invert_jsonl_path: str | None = None

    def folders_for_sig(self, sig: str, *, mesh_only: bool = True) -> list[str]:
        table = self.inverted_mesh if mesh_only else self.inverted_all
        return list(table.get(sig, []))

    def shared_mesh_sigs(self, folder_a: str, folder_b: str) -> list[str]:
        """Distinct mesh signatures posted under both folders (deterministic order)."""
        a = folder_a.replace("\\", "/")
        b = folder_b.replace("\\", "/")
        out: list[str] = []
        for sig, folders in sorted(self.inverted_mesh.items()):
            if a in folders and b in folders:
                out.append(sig)
        return out


def member_signature(basename: str, uncompressed_size: int, crc32: int) -> str:
    """Canonical recall key: basename|uncompressed_size|crc32 (ADR D-2)."""
    base = Path(basename.replace("\\", "/")).name
    return f"{base}|{int(uncompressed_size)}|{int(crc32) & 0xFFFFFFFF}"


def is_mesh_path(member_path: str) -> bool:
    return Path(member_path.replace("\\", "/")).suffix.lower() in MESH_EXT


def is_junk_member(member_path: str) -> bool:
    """Skip AppleDouble / OS junk paths (never contribute to overlap)."""
    norm = member_path.replace("\\", "/").strip("/")
    if not norm:
        return True
    parts = [p for p in norm.split("/") if p]
    lower_parts = [p.lower() for p in parts]
    if any(p == "__macosx" or p.startswith(".__") for p in lower_parts):
        return True
    base = lower_parts[-1] if lower_parts else ""
    if base in _JUNK_BASENAMES:
        return True
    if base.startswith("._"):
        return True
    return False


def _outer_zip_stat(path: Path) -> tuple[int | None, int | None]:
    try:
        st = path.stat()
        return st.st_size, getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))
    except OSError:
        return None, None


def list_zip_members(
    zip_path: Path,
    *,
    folder_rel: str,
    max_members: int = DEFAULT_MAX_MEMBERS_PER_ARCHIVE,
) -> ZipListing:
    """
    List central-directory entries for one zip. Never calls ZipFile.read.

    Bad / unreadable zips return skip_reason and empty members.
    """
    outer_size, outer_mtime_ns = _outer_zip_stat(zip_path)
    listing = ZipListing(
        zip_path=str(zip_path),
        folder_rel=folder_rel.replace("\\", "/"),
        max_members=max_members,
        outer_size=outer_size,
        outer_mtime_ns=outer_mtime_ns,
    )
    if max_members < 1:
        listing.skip_reason = "max_members_lt_1"
        return listing

    try:
        # ZipFile context — infolist only; no .read on this path.
        with zipfile.ZipFile(zip_path, "r") as zf:
            infos = zf.infolist()
            kept = 0
            for info in infos:
                if info.is_dir():
                    continue
                name = info.filename or ""
                if is_junk_member(name):
                    continue
                if kept >= max_members:
                    listing.truncated = True
                    break
                basename = Path(name.replace("\\", "/")).name
                if not basename:
                    continue
                mesh = is_mesh_path(name)
                member = MemberSig(
                    basename=basename,
                    uncompressed_size=int(info.file_size),
                    crc32=int(info.CRC) & 0xFFFFFFFF,
                    is_mesh=mesh,
                    member_path=name.replace("\\", "/"),
                )
                listing.members.append(member)
                if mesh:
                    listing.mesh_count += 1
                kept += 1
    except zipfile.BadZipFile:
        listing.skip_reason = "bad_zip"
        listing.members.clear()
        listing.mesh_count = 0
        listing.truncated = False
    except (OSError, RuntimeError) as exc:
        listing.skip_reason = f"io_error:{type(exc).__name__}"
        listing.members.clear()
        listing.mesh_count = 0
        listing.truncated = False
        log.warning(
            "archive_index skip zip path=%s reason=%s",
            zip_path.name,
            listing.skip_reason,
        )
    return listing


def iter_folder_zips(folder: Path) -> Iterator[Path]:
    """Deterministic zip discovery under a model folder (depth-limited, skip dot dirs)."""
    if not folder.is_dir():
        return
    found: list[Path] = []
    try:
        for p in folder.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in ZIP_EXT:
                continue
            try:
                rel = p.relative_to(folder)
            except ValueError:
                continue
            if any(part.startswith(".") for part in rel.parts[:-1]):
                continue
            found.append(p)
    except OSError:
        return
    for p in sorted(found, key=lambda q: str(q).lower()):
        yield p


def _post(
    table: dict[str, set[str]],
    sig: str,
    folder_rel: str,
) -> None:
    table.setdefault(sig, set()).add(folder_rel)


def _freeze_inverted(raw: dict[str, set[str]]) -> dict[str, list[str]]:
    return {sig: sorted(folders) for sig, folders in sorted(raw.items())}


def build_archive_index(
    cfg: CurateConfig,
    *,
    max_members_per_archive: int = DEFAULT_MAX_MEMBERS_PER_ARCHIVE,
    folders: Iterable[ModelFolder] | None = None,
    write_artifacts: bool = True,
    run_id: str | None = None,
) -> ArchiveIndexResult:
    """
    Walk model folders, list zip interiors, invert sig→folders.

    Export for SPEC-005: use ``result.inverted_mesh`` / ``folders_for_sig`` /
    ``shared_mesh_sigs``. Does not call ``build_merge_candidates``.
    """
    model_folders = list(folders) if folders is not None else iter_model_folders(cfg)
    # Deterministic walk order
    model_folders.sort(key=lambda f: f.rel_posix.lower())

    result = ArchiveIndexResult(folders_scanned=len(model_folders))
    invert_mesh: dict[str, set[str]] = {}
    invert_all: dict[str, set[str]] = {}

    for folder in model_folders:
        rel = folder.rel_posix
        for zpath in iter_folder_zips(folder.path):
            listing = list_zip_members(
                zpath,
                folder_rel=rel,
                max_members=max_members_per_archive,
            )
            result.listings.append(listing)
            if listing.skip_reason:
                result.zips_skipped += 1
                continue
            result.zips_scanned += 1
            if listing.truncated:
                result.zips_truncated += 1
            for member in listing.members:
                _post(invert_all, member.sig, rel)
                if member.is_mesh:
                    _post(invert_mesh, member.sig, rel)

    result.inverted_mesh = _freeze_inverted(invert_mesh)
    result.inverted_all = _freeze_inverted(invert_all)

    if write_artifacts:
        work = cfg.resolved_work_dir()
        work.mkdir(parents=True, exist_ok=True)
        rid = run_id or time.strftime("%Y%m%d-%H%M%S")
        index_path = work / f"{ARCHIVE_INDEX_PREFIX}-{rid}.jsonl"
        invert_path = work / f"{ARCHIVE_INVERT_PREFIX}-{rid}.jsonl"
        write_archive_index_artifacts(result, index_path=index_path, invert_path=invert_path)
        result.index_jsonl_path = str(index_path)
        result.invert_jsonl_path = str(invert_path)
        log.info(
            "archive_index wrote index=%s invert=%s zips=%s skipped=%s truncated=%s",
            index_path.name,
            invert_path.name,
            result.zips_scanned,
            result.zips_skipped,
            result.zips_truncated,
        )

    return result


def write_archive_index_artifacts(
    result: ArchiveIndexResult,
    *,
    index_path: Path,
    invert_path: Path,
) -> None:
    """Write archive-index + archive-invert JSONL under .spark-curate/."""
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8") as fh:
        for listing in result.listings:
            fh.write(json.dumps(listing.to_dict(), ensure_ascii=False) + "\n")

    with invert_path.open("w", encoding="utf-8") as fh:
        # Mesh-prefer inverted postings (SPEC-005 consumption surface).
        for sig, folders in result.inverted_mesh.items():
            fh.write(
                json.dumps(
                    {
                        "sig": sig,
                        "folders": folders,
                        "folder_count": len(folders),
                        "mesh": True,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def run_archive_match(
    cfg: CurateConfig,
    *,
    max_members_per_archive: int = DEFAULT_MAX_MEMBERS_PER_ARCHIVE,
    run_id: str | None = None,
) -> ArchiveIndexResult:
    """MODE=match entrypoint: build index artifacts; no merge apply."""
    return build_archive_index(
        cfg,
        max_members_per_archive=max_members_per_archive,
        write_artifacts=True,
        run_id=run_id,
    )


def summary_dict(result: ArchiveIndexResult) -> dict[str, Any]:
    multi = sum(1 for folders in result.inverted_mesh.values() if len(folders) >= 2)
    return {
        "mode": "match",
        "folders_scanned": result.folders_scanned,
        "zips_scanned": result.zips_scanned,
        "zips_skipped": result.zips_skipped,
        "zips_truncated": result.zips_truncated,
        "mesh_sigs": len(result.inverted_mesh),
        "mesh_sigs_multi_folder": multi,
        "index_jsonl_path": result.index_jsonl_path,
        "invert_jsonl_path": result.invert_jsonl_path,
    }

