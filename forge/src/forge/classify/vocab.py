"""Closed category vocabulary (ADR D-5) and the folder names that are sources, not categories.

INIT-032/SPEC-011
"""

from __future__ import annotations

from forge.db.enums import PACK_CATEGORIES

CATEGORIES: tuple[str, ...] = PACK_CATEGORIES
FALLBACK_CATEGORY = "Misc"
assert FALLBACK_CATEGORY in CATEGORIES
assert "Unknown" not in CATEGORIES

_CATEGORY_BY_FOLD = {c.casefold(): c for c in CATEGORIES}

# Top-level folders that name where a pack came from. They become `source` tags, never folders.
SOURCES: tuple[str, ...] = ("AnySTL", "Cults3D", "Gumroad", "B3dserk", "WICKED")
_SOURCE_BY_FOLD = {s.casefold(): s for s in SOURCES}

# Top-level folders that carry no category or source information.
NON_CATEGORY_FOLDERS = frozenset({"unknown", "@untagged", "untagged", "misc unsorted"})

# datapackage keywords that seed a category deterministically (spark-curate wrote them).
# Generic words ('art', 'tools', 'misc') are deliberately excluded — too ambiguous as keywords.
KEYWORD_CATEGORIES = {
    "anime": "Anime",
    "manga": "Anime",
    "cartoons": "Cartoons",
    "cartoon": "Cartoons",
    "cosplay": "Cosplay",
    "dc": "DC",
    "dc comics": "DC",
    "d&d": "D&D",
    "dnd": "D&D",
    "dungeons and dragons": "D&D",
    "games": "Games",
    "video games": "Games",
    "movie tv": "Movie TV",
    "comics": "Comics",
    "vehicles": "Vehicles",
    "terrain": "Terrain",
    "tabletop": "Tabletop",
}


def folder_category(top: str) -> str | None:
    return _CATEGORY_BY_FOLD.get(top.strip().casefold())


def folder_source(top: str) -> str | None:
    return _SOURCE_BY_FOLD.get(top.strip().casefold())


def keyword_category(keyword: str) -> str | None:
    return KEYWORD_CATEGORIES.get(keyword.strip().casefold())


def source_keyword(keyword: str) -> str | None:
    return _SOURCE_BY_FOLD.get(keyword.strip().casefold())
