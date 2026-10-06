"""Tag review loop: review CSV export, override CSV import, sample, stats.

Overrides are keyed by unit key (the pack's primary unit in the export), so they survive pack id
changes; `forge tags` applies them on every run: ``set`` replaces every derived tag, ``add`` is
appended, ``remove`` is dropped. They are never overwritten by a rerun.

INIT-032/SPEC-016
"""

from __future__ import annotations

import csv
import json
import random
import sys
from collections.abc import Iterable
from typing import TextIO

from sqlalchemy import create_engine, text

from forge.config import require_db_url
from forge.tags.normalize import normalise_tags

REVIEW_COLUMNS = (
    "pack_id",
    "unit_key",
    "category",
    "name",
    "tags",
    "set_tags",
    "add_tags",
    "remove_tags",
    "note",
)
_PRIMARY_UNIT = (
    "(SELECT u.unit_key FROM pack_units u WHERE u.pack_id = p.id "
    "ORDER BY (u.role = 'primary') DESC, u.id LIMIT 1)"
)


class TagOverrideError(ValueError):
    pass


def _engine(db_url: str | None):
    return create_engine(db_url or require_db_url(), pool_pre_ping=True)


def _split(cell: str | None) -> list[str]:
    return [t.strip() for t in (cell or "").replace(",", ";").split(";") if t.strip()]


def export_review(
    out: TextIO, *, db_url: str | None = None, pack_ids: list[int] | None = None
) -> int:
    engine = _engine(db_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT p.id, {_PRIMARY_UNIT} AS unit_key, p.category, p.name, p.tags
                    FROM packs p
                    WHERE p.status <> 'provisional'
                      AND EXISTS (SELECT 1 FROM pack_units u WHERE u.pack_id = p.id)
                      AND (CAST(:ids AS bigint[]) IS NULL OR p.id = ANY(CAST(:ids AS bigint[])))
                    ORDER BY p.id
                    """
                ),
                {"ids": pack_ids or None},
            ).all()
    finally:
        engine.dispose()
    w = csv.DictWriter(out, fieldnames=REVIEW_COLUMNS)
    w.writeheader()
    for pid, unit_key, cat, name, tags in rows:
        w.writerow(
            {
                "pack_id": pid,
                "unit_key": unit_key,
                "category": cat,
                "name": name,
                "tags": ";".join(tags or []),
                "set_tags": "",
                "add_tags": "",
                "remove_tags": "",
                "note": "",
            }
        )
    return len(rows)


def import_overrides(rows: Iterable[dict], *, db_url: str | None = None) -> dict[str, int]:
    """Upsert tag_overrides from CSV rows (columns set_tags / add_tags / remove_tags / note).
    Cells are ``;``-separated; blank cells change nothing."""
    counts = {"imported": 0, "skipped_blank": 0}
    engine = _engine(db_url)
    try:
        with engine.begin() as conn:
            for i, row in enumerate(rows, start=2):
                lists = {}
                for col in ("set_tags", "add_tags", "remove_tags"):
                    items = _split(row.get(col))
                    if not items:
                        lists[col] = None
                        continue
                    tags = normalise_tags(items, cap=None, singular=False)
                    if not tags:
                        raise TagOverrideError(f"line {i}: {col} {items!r} names no usable tag")
                    lists[col] = tags
                note = (row.get("note") or "").strip() or None
                if not any((*lists.values(), note)):
                    counts["skipped_blank"] += 1
                    continue
                key = (row.get("unit_key") or "").strip()
                if not key:
                    raise TagOverrideError(f"line {i}: unit_key is required")
                conn.execute(
                    text(
                        """
                        INSERT INTO tag_overrides (unit_key, add_tags, remove_tags, set_tags, note)
                        VALUES (:k, :a, :r, :s, :n)
                        ON CONFLICT (unit_key) DO UPDATE SET
                            add_tags = coalesce(EXCLUDED.add_tags, tag_overrides.add_tags),
                            remove_tags = coalesce(EXCLUDED.remove_tags, tag_overrides.remove_tags),
                            set_tags = coalesce(EXCLUDED.set_tags, tag_overrides.set_tags),
                            note = coalesce(EXCLUDED.note, tag_overrides.note),
                            created_at = now()
                        """
                    ),
                    {
                        "k": key,
                        "a": lists["add_tags"],
                        "r": lists["remove_tags"],
                        "s": lists["set_tags"],
                        "n": note,
                    },
                )
                counts["imported"] += 1
    finally:
        engine.dispose()
    return counts


def import_csv(path: str, *, db_url: str | None = None) -> dict[str, int]:
    with open(path, newline="", encoding="utf-8") as fh:
        return import_overrides(csv.DictReader(fh), db_url=db_url)


def sample(
    n: int = 20, *, seed: int = 32, db_url: str | None = None, out: TextIO = sys.stdout
) -> int:
    """Print n random tagged packs (JSONL) with the evidence the LLM saw."""
    engine = _engine(db_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT p.id, {_PRIMARY_UNIT} AS unit_key, p.category, p.name, p.tags
                    FROM packs p WHERE p.tags_fingerprint IS NOT NULL ORDER BY p.id
                    """
                )
            ).all()
            picked = random.Random(seed).sample(rows, min(n, len(rows)))
            for i, (pid, unit_key, cat, name, tags) in enumerate(picked, start=1):
                out.write(
                    json.dumps(
                        {
                            "n": i,
                            "pack_id": pid,
                            "unit_key": unit_key,
                            "category": cat,
                            "name": name,
                            "tags": list(tags or []),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    finally:
        engine.dispose()
    return len(picked)


def stats(*, top: int = 30, db_url: str | None = None) -> dict:
    """Tag coverage and distribution over the classified packs."""
    engine = _engine(db_url)
    try:
        with engine.connect() as conn:
            head = (
                conn.execute(
                    text(
                        """
                        SELECT count(*) AS packs,
                               count(*) FILTER (WHERE tags_fingerprint IS NOT NULL) AS tagged,
                               count(*) FILTER (WHERE n = 0) AS tags_0,
                               count(*) FILTER (WHERE n BETWEEN 1 AND 4) AS tags_1_4,
                               count(*) FILTER (WHERE n BETWEEN 5 AND 9) AS tags_5_9,
                               count(*) FILTER (WHERE n BETWEEN 10 AND 14) AS tags_10_14,
                               count(*) FILTER (WHERE n >= 15) AS tags_15_plus
                        FROM (SELECT tags_fingerprint, cardinality(tags) AS n FROM packs
                              WHERE status <> 'provisional') x
                        """
                    )
                )
                .mappings()
                .one()
            )
            llm = conn.execute(
                text(
                    "SELECT count(DISTINCT input_fingerprint) FROM tag_decisions "
                    "WHERE verdict = 'ok'"
                )
            ).scalar_one()
            tops = conn.execute(
                text(
                    """
                    SELECT t, count(*) FROM packs p, unnest(p.tags) t
                    WHERE p.status <> 'provisional' GROUP BY t ORDER BY 2 DESC, t LIMIT :n
                    """
                ),
                {"n": top},
            ).all()
            distinct = conn.execute(
                text(
                    "SELECT count(DISTINCT t) FROM packs p, unnest(p.tags) t "
                    "WHERE p.status <> 'provisional'"
                )
            ).scalar_one()
    finally:
        engine.dispose()
    return {
        **{k: int(v) for k, v in head.items()},
        "llm_decisions_ok": int(llm),
        "distinct_tags": int(distinct),
        "top_tags": [[t, int(n)] for t, n in tops],
    }
