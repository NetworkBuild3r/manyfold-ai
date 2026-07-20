# candidates.py — build merge candidate pairs from filesystem heuristics
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import CurateConfig
from .preview import ARCHIVE_EXT, IMAGE_EXT
from .walk import MODEL_EXT, ModelFolder, iter_model_folders

# Foo (2), Foo (3), Foo_copy, Foo - Copy
_NEAR_DUPE_SUFFIX = re.compile(
    r"[\s_\-]*(?:\(\d+\)|copy(?:\s*\d+)?|copy of)\s*$",
    re.IGNORECASE,
)


@dataclass
class FolderFingerprint:
    folder: ModelFolder
    # basename.lower() -> set of sizes (bytes)
    files: dict[str, set[int]] = field(default_factory=dict)
    # quick content signatures for small non-archive files: (name, size, sha256_16)
    digests: set[str] = field(default_factory=set)


@dataclass
class MergeCandidate:
    a: ModelFolder
    b: ModelFolder
    signals: list[str]

    @property
    def pair_key(self) -> tuple[str, str]:
        paths = sorted([self.a.rel_posix.lower(), self.b.rel_posix.lower()])
        return (paths[0], paths[1])


def normalize_model_slug(name: str) -> str:
    n = name.strip().lower()
    n = _NEAR_DUPE_SUFFIX.sub("", n)
    n = re.sub(r"[^a-z0-9]+", "", n)
    return n


def _sample_file_meta(folder: Path, limit: int = 80) -> tuple[dict[str, set[int]], set[str]]:
    files: dict[str, set[int]] = {}
    digests: set[str] = set()
    count = 0
    try:
        for p in sorted(folder.rglob("*")):
            if not p.is_file():
                continue
            if any(part.startswith(".") for part in p.relative_to(folder).parts):
                continue
            ext = p.suffix.lower()
            if ext not in MODEL_EXT and ext not in IMAGE_EXT and ext not in ARCHIVE_EXT:
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            key = p.name.lower()
            files.setdefault(key, set()).add(size)
            # Cheap digest for small non-archives (helps true duplicates)
            if ext not in ARCHIVE_EXT and 0 < size <= 2_000_000:
                try:
                    h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
                    digests.add(f"{key}:{size}:{h}")
                except OSError:
                    pass
            count += 1
            if count >= limit:
                break
    except OSError:
        pass
    return files, digests


def fingerprint(folder: ModelFolder) -> FolderFingerprint:
    files, digests = _sample_file_meta(folder.path)
    return FolderFingerprint(folder=folder, files=files, digests=digests)


def _name_near_dupe(a: ModelFolder, b: ModelFolder) -> bool:
    if a.category.lower() != b.category.lower():
        return False
    sa, sb = normalize_model_slug(a.name), normalize_model_slug(b.name)
    if not sa or not sb:
        return False
    if sa == sb and a.name.lower() != b.name.lower():
        return True
    # One name is the other plus a near-dupe suffix already stripped → equal slug
    return sa == sb


def _shared_digests(fa: FolderFingerprint, fb: FolderFingerprint) -> set[str]:
    return fa.digests & fb.digests


def _basename_size_overlap(fa: FolderFingerprint, fb: FolderFingerprint) -> int:
    """Count filenames that share at least one identical size in both folders."""
    n = 0
    for name, sizes_a in fa.files.items():
        sizes_b = fb.files.get(name)
        if sizes_b and (sizes_a & sizes_b):
            n += 1
    return n


def build_merge_candidates(
    cfg: CurateConfig,
    *,
    max_pairs: int | None = None,
) -> list[MergeCandidate]:
    """
    Build candidate pairs. Same franchise/name alone is NOT enough —
    we require name_near_dupe and/or file overlap signals.
    """
    folders = iter_model_folders(cfg)
    fps = [fingerprint(f) for f in folders]
    by_slug: dict[tuple[str, str], list[FolderFingerprint]] = {}
    for fp in fps:
        slug = normalize_model_slug(fp.folder.name)
        key = (fp.folder.category.lower(), slug)
        by_slug.setdefault(key, []).append(fp)

    seen: set[tuple[str, str]] = set()
    out: list[MergeCandidate] = []
    cap = max_pairs if max_pairs is not None else (cfg.max_merge_pairs or 200)

    # Pass 1: name near-dupes in same category
    for group in by_slug.values():
        if len(group) < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                fa, fb = group[i], group[j]
                if not _name_near_dupe(fa.folder, fb.folder):
                    # same slug after normalize always near-dupe if names differ
                    if normalize_model_slug(fa.folder.name) != normalize_model_slug(fb.folder.name):
                        continue
                    if fa.folder.name.lower() == fb.folder.name.lower():
                        continue
                signals = ["name_near_dupe"]
                shared = _shared_digests(fa, fb)
                if shared:
                    signals.append("shared_digest")
                overlap = _basename_size_overlap(fa, fb)
                if overlap >= 1:
                    signals.append(f"basename_size_overlap:{overlap}")
                cand = MergeCandidate(a=fa.folder, b=fb.folder, signals=signals)
                if cand.pair_key in seen:
                    continue
                seen.add(cand.pair_key)
                out.append(cand)
                if len(out) >= cap:
                    return out

    # Pass 2: strong file overlap without name match (true re-downloads with different folder names)
    for i in range(len(fps)):
        for j in range(i + 1, len(fps)):
            fa, fb = fps[i], fps[j]
            cand = MergeCandidate(a=fa.folder, b=fb.folder, signals=[])
            if cand.pair_key in seen:
                continue
            shared = _shared_digests(fa, fb)
            overlap = _basename_size_overlap(fa, fb)
            signals: list[str] = []
            if shared:
                signals.append("shared_digest")
            if overlap >= 3:
                signals.append(f"basename_size_overlap:{overlap}")
            # Require strong overlap — never pair solely on category/franchise
            if not signals:
                continue
            if "shared_digest" not in signals and overlap < 3:
                continue
            cand.signals = signals
            seen.add(cand.pair_key)
            out.append(cand)
            if len(out) >= cap:
                return out

    return out
