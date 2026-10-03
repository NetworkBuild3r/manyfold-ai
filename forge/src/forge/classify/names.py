"""Pack display / folder names: cleanup, filesystem safety, deterministic disambiguation.

A folder name never contains '/', '\\', control characters, Windows-reserved characters, or
leading/trailing dots/spaces; it is <= 120 characters and <= 240 UTF-8 bytes; it never ends in a
' (N)' counter. Collisions inside one category are resolved by appending the creator, then the
source, then an 8-hex hash of the pack's anchor unit key — never '(2)'.

INIT-032/SPEC-011
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass

MAX_CHARS = 120
MAX_BYTES = 240

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_UNSAFE = re.compile(r'[/\\*?"<>|]')
_ARCHIVE_EXT = re.compile(
    r"(?:(?:\.part\d+)?\.(?:zip|rar|7z|tar|tgz|gz|bz2|xz|zst|lz4|cab)(?:\.\d{1,3})?"
    r"|\.(?:\d{3}|z\d{2}|r\d{2}))$",
    re.I,
)
_COUNTER = re.compile(r"\s*\(\s*\d{1,4}\s*\)\s*$")
_COPY = re.compile(r"\s+-\s+copy(?:\s*\(\d+\))?\s*$", re.I)
_PART = re.compile(r"[\s._-]*\b(?:part|pt)[\s._-]*\d{1,3}\s*$", re.I)
_DATE = re.compile(
    r"(?<!\d)(?:19|20)\d{2}[-_.](?:0[1-9]|1[0-2])(?:[-_.](?:0[1-9]|[12]\d|3[01]))?(?!\d)"
)
_COMPACT_DATE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:[0-2]\d|3[01])(?!\d)")
_PREFIX = re.compile(r"^(?:attachment[_ -]+)", re.I)
_SEP_RUN = re.compile(r"(?:\s*[-–]\s*){2,}")
_TRAIL = re.compile(r"[\s\-_.,;:~+&#@]+$")
_LEAD = re.compile(r"^[\s\-_.,;:~+]+")
_WS = re.compile(r"\s+")
_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com\d|lpt\d)$", re.I)
_GENERIC = {
    "stl",
    "stls",
    "stl files",
    "files",
    "file",
    "model",
    "models",
    "supported",
    "unsupported",
    "presupported",
    "pre-supported",
    "print",
    "prints",
    "parts",
    "new folder",
    "untitled",
    "obj",
    "lys",
    "chitubox",
    "img",
    "images",
    "renders",
    "unnamed",
    "unnamed-model",
    "unnamed model",
    "untitled model",
    "no name",
}


def strip_archive_ext(name: str) -> str:
    prev = None
    while prev != name:
        prev = name
        name = _ARCHIVE_EXT.sub("", name)
    return name


def fs_safe(name: str) -> str:
    """Make a single path component safe (no separators, control chars, reserved names)."""
    name = unicodedata.normalize("NFC", name)
    name = _CONTROL.sub(" ", name)
    name = name.replace(":", " - ")
    name = _UNSAFE.sub(" ", name)
    name = _WS.sub(" ", name).strip()
    name = name.strip(". ")
    if _RESERVED.match(name):
        name += "_"
    return name


def clamp(name: str, max_chars: int = MAX_CHARS, max_bytes: int = MAX_BYTES) -> str:
    if len(name) > max_chars:
        cut = name[:max_chars]
        space = cut.rfind(" ")
        name = cut[:space] if space >= max_chars * 2 // 3 else cut
    while len(name.encode("utf-8")) > max_bytes:
        name = name[:-1]
    return _TRAIL.sub("", name).strip(". ")


def clean_name(raw: str, *, keep_dates: bool = False) -> str:
    """Human display name from a folder / archive / title string ('' when nothing usable).

    keep_dates=True is the disambiguation variant: it keeps dates and 'part N' because monthly
    releases ('GoonMaster 2020-08') or split releases ('Man Eaters Part 1') differ only there."""
    name = unicodedata.normalize("NFC", raw or "")
    name = _CONTROL.sub(" ", name)
    name = strip_archive_ext(name.strip())
    if " " not in name and ("_" in name or "+" in name):
        name = name.replace("_", " ").replace("+", " ")
    name = _PREFIX.sub("", name)
    if not keep_dates:
        name = _DATE.sub(" ", name)
        name = _COMPACT_DATE.sub(" ", name)
    for _ in range(3):
        before = name
        name = _WS.sub(" ", name).strip()
        name = _COUNTER.sub("", name)
        name = _COPY.sub("", name)
        if not keep_dates:
            name = _PART.sub("", name)
        name = _TRAIL.sub("", name)
        if name == before:
            break
    name = _SEP_RUN.sub(" - ", name)
    name = _LEAD.sub("", _TRAIL.sub("", name))
    return finalize(name)


def finalize(name: str) -> str:
    """fs_safe + clamp until stable (truncation can expose a counter or trailing junk)."""
    for _ in range(5):
        before = name
        name = fs_safe(name)
        name = clamp(name)
        name = _COUNTER.sub("", name)
        name = _LEAD.sub("", _TRAIL.sub("", name))
        if name == before:
            break
    if _RESERVED.match(name):
        name += "_"
    return name


def is_weak(name: str) -> bool:
    letters = sum(1 for ch in name if ch.isalpha())
    return letters < 3 or name.strip().lower() in _GENERIC


def hash8(anchor_key: str) -> str:
    return hashlib.sha256(anchor_key.encode()).hexdigest()[:8]


def _with_suffix(base: str, suffix: str) -> str:
    suffix = fs_safe(suffix)
    room = MAX_CHARS - len(suffix) - 3
    trimmed = clamp(base, max_chars=max(8, room), max_bytes=MAX_BYTES - len(suffix.encode()) - 3)
    return f"{trimmed} - {suffix}"


@dataclass
class NameRequest:
    pack_id: int
    category: str
    base: str
    anchor_key: str
    creator: str | None = None
    source: str | None = None
    current: str | None = None
    alternates: tuple[str, ...] = ()


def assign_names(requests: Iterable[NameRequest]) -> dict[int, str]:
    """Unique (case-insensitive) folder names per category. Candidates in order: base, base -
    creator, base - source, alternates (e.g. the dated variant), base - hash8. Deterministic and
    sticky: a pack that already holds a still-valid candidate keeps it; the rest go in anchor-key
    order."""
    by_cat: dict[str, list[NameRequest]] = {}
    for r in requests:
        by_cat.setdefault(r.category, []).append(r)
    out: dict[int, str] = {}
    for reqs in by_cat.values():
        used: set[str] = set()
        cands: dict[int, list[str]] = {}
        bases = {r.pack_id: finalize(r.base) or f"Pack {hash8(r.anchor_key)}" for r in reqs}
        demand: dict[str, int] = {}
        for b in bases.values():
            demand[b.casefold()] = demand.get(b.casefold(), 0) + 1
        for r in reqs:
            base = bases[r.pack_id]
            alts = [a for a in r.alternates if a and a.casefold() != base.casefold()]
            options = alts if demand[base.casefold()] > 1 else []
            options = [*options, base]
            if r.creator and r.creator.casefold() not in base.casefold():
                options.append(_with_suffix(base, r.creator))
            if r.source and r.source.casefold() not in base.casefold():
                options.append(_with_suffix(base, r.source))
            options.extend(a for a in alts if a not in options)
            options.append(_with_suffix(base, hash8(r.anchor_key)))
            cands[r.pack_id] = [o for o in (finalize(x) for x in options) if o]
        ordered = sorted(reqs, key=lambda r: r.anchor_key)
        sticky = [r for r in ordered if r.current and r.current in cands[r.pack_id]]
        for r in sticky:
            key = r.current.casefold()
            if key not in used:
                used.add(key)
                out[r.pack_id] = r.current
        for r in ordered:
            if r.pack_id in out:
                continue
            for opt in cands[r.pack_id]:
                if opt.casefold() not in used:
                    used.add(opt.casefold())
                    out[r.pack_id] = opt
                    break
            else:
                opt = _with_suffix(cands[r.pack_id][0], f"{hash8(r.anchor_key)}-{r.pack_id}")
                used.add(opt.casefold())
                out[r.pack_id] = opt
    return out
