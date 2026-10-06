"""v2 layout and path sanitization (pure functions, no I/O).

``<v2>/<Category>/<Pack>/<relative path inside source>`` (ADR D-5). Every component is NFC,
free of control characters and separators, never ``.``/``..``/empty, never dot-hidden, and at
most 255 UTF-8 bytes. Collisions inside a pack are resolved deterministically by appending
``~<sha prefix>`` to the stem, so a file's name does not depend on processing order.
"""

from __future__ import annotations

import hashlib
import posixpath
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from forge.db.enums import PACK_CATEGORIES

MAX_COMPONENT_BYTES = 255
# Relative to the v2 root. PATH_MAX is 4096; the Job mounts v2 at a short prefix
# (/nas/3D-Prints-v2).
MAX_REL_PATH_BYTES = 3800
DATAPACKAGE = "datapackage.json"
FALLBACK_CATEGORY = "Misc"

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ARCHIVE_SUFFIX = re.compile(
    r"(\.part\d+)?\.(zip|rar|7z|tar|tgz|tbz2?|txz|gz|bz2|xz|zst|lz4|cab|cbz|cbr|iso|r\d\d|\d{3})$",
    re.IGNORECASE,
)
_TAR_INNER = re.compile(r"\.tar$", re.IGNORECASE)


def _utf8_len(s: str) -> int:
    return len(s.encode("utf-8"))


def _truncate_utf8(s: str, limit: int) -> str:
    b = s.encode("utf-8")
    if len(b) <= limit:
        return s
    return b[:limit].decode("utf-8", errors="ignore")


def split_ext(name: str) -> tuple[str, str]:
    """``("model", ".stl")``; dotfiles and long pseudo-extensions keep everything in the stem."""
    stem, ext = posixpath.splitext(name)
    if not stem or len(ext) > 17:
        return name, ""
    return stem, ext


def sanitize_component(name: str) -> str:
    """One safe path component. Deterministic; never returns ``""``, ``.`` or ``..``."""
    s = name.encode("utf-8", errors="replace").decode("utf-8")  # lone surrogates -> '?'
    s = unicodedata.normalize("NFC", s)
    s = _CONTROL.sub("_", s).replace("/", "_").replace("\\", "_").strip()
    if s in ("", ".", ".."):
        s = "_" if not s else "_" * len(s)
    if s.startswith("."):
        s = "_" + s[1:]  # dot-hidden names are invisible to Manyfold's scanner
    if _utf8_len(s) > MAX_COMPONENT_BYTES:
        tag = "~" + hashlib.sha256(name.encode("utf-8", "replace")).hexdigest()[:8]
        stem, ext = split_ext(s)
        if _utf8_len(ext) > 32:
            stem, ext = s, ""
        room = MAX_COMPONENT_BYTES - _utf8_len(tag) - _utf8_len(ext)
        s = _truncate_utf8(stem, room).rstrip() + tag + ext
    return s


def category_dir(category: str | None) -> str:
    """Closed list (ADR D-5); anything else (incl. NULL = not yet classified) -> ``Misc``."""
    return category if category in PACK_CATEGORIES else FALLBACK_CATEGORY


def pack_folder_name(name: str | None, pack_id: int) -> str:
    base = (name or "").strip()
    return sanitize_component(base if base else f"pack-{pack_id}")


def strip_archive_suffix(name: str) -> str:
    """Folder name for a nested archive's members: ``inner.zip`` -> ``inner``."""
    out = _TAR_INNER.sub("", _ARCHIVE_SUFFIX.sub("", name))
    return out or name


def chain_components(chain: Sequence[str]) -> list[str]:
    """Path components for a member chain. Archive elements (all but the last) become folders
    named after the archive without its suffix; ``//dupN`` markers are dropped (a duplicate name
    collides and is resolved by :func:`resolve_collisions`)."""
    out: list[str] = []
    for i, element in enumerate(chain):
        element = element.split("//", 1)[0]
        parts = [p for p in element.replace("\\", "/").split("/") if p not in ("", ".")]
        if not parts:
            parts = ["_"]
        if i < len(chain) - 1:
            parts[-1] = strip_archive_suffix(parts[-1])
        out.extend(parts)
    return out


def is_junk(components: Sequence[str]) -> bool:
    """macOS archive debris: ``__MACOSX/`` trees and AppleDouble ``._name`` files (4 KiB
    resource forks that carry a mesh extension but are not meshes)."""
    return any(c == "__MACOSX" for c in components) or (
        bool(components) and components[-1].startswith("._")
    )


def sanitize_components(components: Iterable[str]) -> list[str]:
    return [sanitize_component(c) for c in components]


def with_tag(rel: str, sha: str, n: int) -> str:
    head, tail = posixpath.split(rel)
    stem, ext = split_ext(tail)
    tagged = sanitize_component(f"{stem}~{sha[:n]}{ext}")
    return posixpath.join(head, tagged) if head else tagged


def _key(rel: str) -> str:
    return unicodedata.normalize("NFC", rel).casefold()


@dataclass(frozen=True)
class Candidate:
    rel: str  # sanitized, '/'-joined, relative to the pack folder
    sha: str


def resolve_collisions(cands: Sequence[Candidate], pack_dir: str) -> dict[str, str]:
    """``sha -> final rel path`` for one pack. ``cands`` must be in priority order and hold one
    entry per sha. A path clashing (case-insensitively) with an earlier file, with a directory
    another file needs, or with ``datapackage.json`` gets ``~<sha8>`` (then ``~<sha16>``, then the
    full sha). Paths longer than the budget move to ``_long/<sha16><ext>``."""
    files: set[str] = {_key(DATAPACKAGE)}
    dirs: set[str] = set()
    out: dict[str, str] = {}
    budget = MAX_REL_PATH_BYTES - _utf8_len(pack_dir) - 1

    def clashes(rel: str) -> bool:
        k = _key(rel)
        if k in files or k in dirs:
            return True
        parts = k.split("/")
        return any("/".join(parts[:i]) in files for i in range(1, len(parts)))

    for c in cands:
        rel = c.rel
        if _utf8_len(rel) > budget:
            rel = "_long/" + c.sha[:16] + split_ext(posixpath.basename(rel))[1]
        ext = split_ext(posixpath.basename(rel))[1]
        trials = [rel] + [with_tag(rel, c.sha, n) for n in (8, 16, 64)]
        # A parent directory clashing with a file cannot be fixed by tagging the basename.
        trials.append(sanitize_component(f"_conflict~{c.sha[:16]}{ext}"))
        trials.append(sanitize_component(f"_conflict~{c.sha}{ext}"))
        for trial in trials:
            if not clashes(trial):
                rel = trial
                break
        else:  # pragma: no cover - a full sha at the pack root is unique per pack
            raise ValueError(f"unresolvable collision for {c.sha} at {rel}")
        out[c.sha] = rel
        k = _key(rel)
        files.add(k)
        parts = k.split("/")
        for i in range(1, len(parts)):
            dirs.add("/".join(parts[:i]))
    return out
