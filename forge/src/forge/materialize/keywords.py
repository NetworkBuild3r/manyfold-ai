"""``datapackage.json`` ``keywords`` — the standard Frictionless array Manyfold reads as model tags.

Pure (no filesystem, no database), so both ``apply`` (new packs) and ``refresh-datapackage``
(already-materialized packs) build the identical list.

* A pack ``forge tags`` has run for (``tagged``) is described by its ``packs.tags`` alone: that list
  already carries category, creator and source as normalised tags.
* An untagged pack keeps the pre-SPEC-016 behaviour: ``[category, source_tag, creator]`` — never the
  raw spark-curate keywords classify stored.

Manyfold side (``rake manyfold:apply_datapackages``, ``DataPackage::ModelDeserializer``):
``keywords`` becomes ``tag_list``; the task is additive (existing tags are kept and the new ones
are appended, case-insensitively), so tags a user edited in Manyfold are never removed.

INIT-032/SPEC-016
"""

from __future__ import annotations

from collections.abc import Iterable


def pack_keywords(
    *,
    category: str | None,
    source_tag: str | None,
    creator: str | None,
    tags: Iterable[str] | None,
    tagged: bool,
) -> list[str]:
    base = list(tags or []) if tagged else [category, source_tag, creator]
    seen: set[str] = set()
    out: list[str] = []
    for item in base:
        if not item:
            continue
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out
