"""Deterministic tags: facts the catalog already holds, turned into tags by explicit rules.

Code derives facts, the LLM only judges (myaifitness-deterministic-compute spirit). Nothing here
touches the network or a database, and nothing here routes anything: every function maps pack
facts (names and paths) to metadata tags for search. The tables below are the whole rulebook.

Tags, in output order: category, creator, source, file formats, supports, scale, part kinds,
``has-preview``.

INIT-032/SPEC-016
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from forge.classify.vocab import FALLBACK_CATEGORY
from forge.tags.normalize import normalise_tag, normalise_tags

RULES_VERSION = "tags-rules-v2"

# --- file formats: extension -> tag (extensions without a dot, lowercase) ---------------------
FORMAT_TAGS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("stl", ("stl",)),
    ("3mf", ("3mf",)),
    ("obj", ("obj",)),
    ("step", ("step", "stp")),
    ("lychee", ("lys", "lyt", "lychee")),
    ("chitubox", ("ctb", "cbddlp", "chitubox")),
    ("gcode", ("gcode", "bgcode")),
    ("blend", ("blend",)),
    ("fbx", ("fbx",)),
)
MESH_EXTS = frozenset(
    {"stl", "obj", "3mf", "ply", "step", "stp", "fbx", "blend", "glb", "gltf", "lys", "lyt"}
)
IMAGE_EXTS = frozenset({"jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff", "heic"})

# --- scale ------------------------------------------------------------------------------------
MM_RANGE = range(6, 201)  # a "28mm" / "75mm" style token
RATIOS = frozenset({2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 16, 18, 20, 24, 32, 35, 48, 72})

# --- supports ---------------------------------------------------------------------------------
PRESUPPORTED = "presupported"
UNSUPPORTED = "unsupported"

# --- part kinds: path word -> tag (singular and plural spellings spelled out) -----------------
PART_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bust", ("bust", "busts")),
    ("base", ("base", "bases")),
    ("head", ("head", "heads")),
    ("torso", ("torso", "torsos")),
    ("arm", ("arm", "arms")),
    ("leg", ("leg", "legs")),
    ("hand", ("hand", "hands")),
    ("wing", ("wing", "wings")),
    ("tail", ("tail", "tails")),
    ("helmet", ("helmet", "helmets")),
    ("shield", ("shield", "shields")),
    ("cape", ("cape", "capes")),
    ("weapon", ("weapon", "weapons")),
)
_PART_BY_WORD = {w: tag for tag, words in PART_WORDS for w in words}


@dataclass(frozen=True)
class PackFacts:
    """What the catalog knows about one pack (names and paths only)."""

    category: str | None = None
    creator: str | None = None
    source_tag: str | None = None
    name: str | None = None
    unit_paths: tuple[str, ...] = ()
    member_paths: tuple[str, ...] = ()
    image_count: int = 0


# ------------------------------------------------------------------------------- tokenising


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric words; a camelCase boundary also splits (``PreSupported`` ->
    ``pre``, ``supported``; ``STLFiles`` -> ``stl``, ``files``). Digits stay attached
    (``32mm`` is one word)."""
    words: list[str] = []
    cur: list[str] = []
    chars = text
    for i, ch in enumerate(chars):
        if not (ch.isascii() and ch.isalnum()):
            if cur:
                words.append("".join(cur).lower())
                cur = []
            continue
        if cur:
            prev = chars[i - 1]
            nxt = chars[i + 1] if i + 1 < len(chars) else ""
            after = chars[i + 2] if i + 2 < len(chars) else ""
            acronym_plural = nxt == "s" and not after.islower()  # "STLs" is one word
            if (prev.islower() and ch.isupper()) or (
                prev.isupper() and ch.isupper() and nxt.islower() and not acronym_plural
            ):
                words.append("".join(cur).lower())
                cur = []
        cur.append(ch)
    if cur:
        words.append("".join(cur).lower())
    return words


def components(path: str) -> list[str]:
    """Path components worth reading: no macOS debris (``__MACOSX``, ``._name``), no empties."""
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    if any(p == "__MACOSX" for p in parts):
        return []
    return [p for p in parts if not p.startswith("._")]


def extension(path: str) -> str:
    base = path.replace("\\", "/").rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base.strip(".") else ""


def _stem(component: str) -> str:
    return component.rsplit(".", 1)[0] if "." in component.strip(".") else component


# ------------------------------------------------------------------------------ simple tags


def category_tag(category: str | None) -> list[str]:
    if not category or category == FALLBACK_CATEGORY:
        return []
    tag = normalise_tag(category, singular=False)
    return [tag] if tag else []


def creator_tag(creator: str | None) -> list[str]:
    tag = normalise_tag(creator, singular=False) if creator else None
    return [tag] if tag else []


def source_tag(source: str | None) -> list[str]:
    tag = normalise_tag(source, singular=False) if source else None
    return [tag] if tag else []


# --------------------------------------------------------------------------- file formats


def format_tags(paths: Iterable[str]) -> list[str]:
    """One tag per file format present, in the fixed table order."""
    exts = {extension(p) for p in paths}
    return [tag for tag, spellings in FORMAT_TAGS if exts.intersection(spellings)]


# ------------------------------------------------------------------------------- supports


def support_flags(words: list[str]) -> tuple[bool, bool]:
    """(presupported, unsupported) for the words of ONE path component."""
    pre = un = False
    i = 0
    while i < len(words):
        w = words[i]
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if w == UNSUPPORTED:
            un = True
        elif w in ("no", "non", "un", "without") and nxt in ("supported", "support", "supports"):
            un = True
            i += 1
        elif w == PRESUPPORTED:
            pre = True
        elif w in ("pre", "with") and nxt in ("supported", "support", "supports"):
            pre = True
            i += 1
        elif w == "supported":
            pre = True
        i += 1
    return pre, un


def support_tags(paths: Iterable[str]) -> list[str]:
    pre = un = False
    for path in paths:
        for comp in components(path):
            p, u = support_flags(tokenize(_stem(comp)))
            pre, un = pre or p, un or u
    return [t for t, on in ((PRESUPPORTED, pre), (UNSUPPORTED, un)) if on]


# ---------------------------------------------------------------------------------- scale


def _mm_tags(words: list[str]) -> set[int]:
    found: set[int] = set()
    for i, w in enumerate(words):
        digits = ""
        if w.endswith("mm") and w[:-2].isdigit():
            digits = w[:-2]
        elif w.isdigit() and i + 1 < len(words) and words[i + 1] == "mm":
            digits = w
        if digits and int(digits) in MM_RANGE:
            found.add(int(digits))
    return found


def _ratio_colon(text: str) -> set[int]:
    """``1:10`` written with a colon inside one component."""
    found: set[int] = set()
    for i, ch in enumerate(text):
        if ch != "1" or (i > 0 and text[i - 1].isdigit()) or text[i + 1 : i + 2] != ":":
            continue
        j = i + 2
        while j < len(text) and text[j].isdigit():
            j += 1
        digits = text[i + 2 : j]
        if digits and int(digits) in RATIOS:
            found.add(int(digits))
    return found


def _ratio_words(words: list[str]) -> set[int]:
    """``1 10 scale`` / ``scale 1 10`` (``1_10_scale``, ``Scale-1-6``)."""
    found: set[int] = set()
    for i in range(len(words) - 2):
        a, b, c = words[i : i + 3]
        if a == "1" and b.isdigit() and c == "scale" and int(b) in RATIOS:
            found.add(int(b))
        if a == "scale" and b == "1" and c.isdigit() and int(c) in RATIOS:
            found.add(int(c))
    return found


def scale_tags(texts: Iterable[str]) -> list[str]:
    """``28mm`` style tags (sorted by size) then ``scale-1-N`` tags (sorted by N)."""
    mm: set[int] = set()
    ratios: set[int] = set()
    for text in texts:
        for comp in components(text):
            stem = _stem(comp)
            words = tokenize(stem)
            mm |= _mm_tags(words)
            ratios |= _ratio_colon(stem) | _ratio_words(words)
    return [f"{n}mm" for n in sorted(mm)] + [f"scale-1-{n}" for n in sorted(ratios)]


# ---------------------------------------------------------------------------------- parts


def part_tags(paths: Iterable[str]) -> list[str]:
    """Part kinds named by a directory or file name of a MESH file, in the fixed table order."""
    seen: set[str] = set()
    for path in paths:
        if extension(path) not in MESH_EXTS:
            continue
        comps = components(path)
        for k, comp in enumerate(comps):
            stem = _stem(comp) if k == len(comps) - 1 else comp
            for w in tokenize(stem):
                tag = _PART_BY_WORD.get(w)
                if tag:
                    seen.add(tag)
    return [tag for tag, _words in PART_WORDS if tag in seen]


def preview_tag(paths: Iterable[str], image_count: int = 0) -> list[str]:
    if image_count > 0 or any(extension(p) in IMAGE_EXTS and components(p) for p in paths):
        return ["has-preview"]
    return []


# ----------------------------------------------------------------------------------- all


def derive_tags(facts: PackFacts) -> list[str]:
    """Every deterministic tag for the pack, normalised and de-duplicated, in rulebook order."""
    paths = [p for p in facts.member_paths if components(p)]
    scale_texts = [t for t in (facts.name or "", *facts.unit_paths, *paths) if t]
    tags = [
        *category_tag(facts.category),
        *creator_tag(facts.creator),
        *source_tag(facts.source_tag),
        *format_tags(paths),
        *support_tags([*facts.unit_paths, *paths]),
        *scale_tags(scale_texts),
        *part_tags(paths),
        *preview_tag(paths, facts.image_count),
    ]
    return normalise_tags(tags, cap=None, singular=False)
