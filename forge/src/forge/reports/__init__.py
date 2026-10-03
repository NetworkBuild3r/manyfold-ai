"""Inventory and cross-pack duplicate reports. INIT-032/SPEC-009.

JSON artifacts are the SPEC-014 input. ``schema_version`` is part of the
contract — bump it only with a documented, additive change.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

# First path component treated as a marketplace / source tag (ASMT-018).
SOURCE_TAGS = (
    "anystl",
    "cults3d",
    "gumroad",
    "b3dserk",
    "myminifactory",
    "printables",
    "thingiverse",
)

__all__ = ["SCHEMA_VERSION", "SOURCE_TAGS"]
