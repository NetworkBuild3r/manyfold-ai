"""Classification review loop: review CSV export, override CSV import, audit sample.

Overrides are keyed by unit key (the pack's primary unit in the export), so they survive pack id
changes; `forge classify` applies them on every run and marks the pack decided_by='human'.

INIT-032/SPEC-011
"""

from __future__ import annotations

import csv
import json
import random
import sys
from collections.abc import Iterable
from typing import TextIO

from sqlalchemy import create_engine, text

from forge.classify.vocab import CATEGORIES
from forge.config import require_db_url

REVIEW_COLUMNS = (
    "pack_id",
    "unit_key",
    "paths",
    "category",
    "name",
    "creator",
    "source_tag",
    "tags",
    "review_reasons",
    "set_category",
    "set_name",
    "set_creator",
    "set_tags",
    "note",
)


class ClassifyOverrideError(ValueError):
    pass


def _engine(db_url: str | None):
    return create_engine(db_url or require_db_url(), pool_pre_ping=True)


def _pack_rows(conn, where: str) -> list:
    return conn.execute(
        text(
            f"""
            SELECT p.id, p.category, p.name, p.creator, p.source_tag, p.tags, p.review_reasons,
                   p.decided_by, p.classify_confidence, p.classify_fingerprint,
                   (SELECT u.unit_key FROM pack_units u WHERE u.pack_id = p.id
                    ORDER BY (u.role = 'primary') DESC, u.id LIMIT 1) AS unit_key,
                   ARRAY(SELECT u.path FROM pack_units u WHERE u.pack_id = p.id
                         ORDER BY u.mesh_bytes DESC, u.id LIMIT 8) AS paths
            FROM packs p WHERE p.status <> 'provisional' AND {where}
            ORDER BY p.id
            """
        )
    ).all()


def export_review(out: TextIO, *, db_url: str | None = None) -> int:
    engine = _engine(db_url)
    try:
        with engine.connect() as conn:
            rows = _pack_rows(
                conn, "EXISTS (SELECT 1 FROM unnest(p.review_reasons) r WHERE r LIKE 'classify_%')"
            )
    finally:
        engine.dispose()
    w = csv.DictWriter(out, fieldnames=REVIEW_COLUMNS)
    w.writeheader()
    for pid, cat, name, creator, source, tags, reasons, *_rest, unit_key, paths in rows:
        w.writerow(
            {
                "pack_id": pid,
                "unit_key": unit_key,
                "paths": " | ".join(paths or []),
                "category": cat,
                "name": name,
                "creator": creator,
                "source_tag": source,
                "tags": ";".join(tags or []),
                "review_reasons": ";".join(reasons or []),
                "set_category": "",
                "set_name": "",
                "set_creator": "",
                "set_tags": "",
                "note": "",
            }
        )
    return len(rows)


def import_overrides(rows: Iterable[dict], *, db_url: str | None = None) -> dict[str, int]:
    """Upsert classify_overrides. Uses set_* columns when present (review CSV), else plain ones."""
    counts = {"imported": 0, "skipped_blank": 0}
    engine = _engine(db_url)
    try:
        with engine.begin() as conn:
            for i, row in enumerate(rows, start=2):

                def col(name: str, row=row) -> str | None:
                    if f"set_{name}" in row:
                        v = row.get(f"set_{name}")
                    else:
                        v = row.get(name)
                    v = (v or "").strip()
                    return v or None

                key = (row.get("unit_key") or "").strip()
                cat, name, creator, tags = col("category"), col("name"), col("creator"), col("tags")
                if not any((cat, name, creator, tags)):
                    counts["skipped_blank"] += 1
                    continue
                if not key:
                    raise ClassifyOverrideError(f"line {i}: unit_key is required")
                if cat and cat not in CATEGORIES:
                    raise ClassifyOverrideError(
                        f"line {i}: category {cat!r} is not in the closed list"
                    )
                tag_list = [t.strip() for t in tags.split(";") if t.strip()] if tags else None
                conn.execute(
                    text(
                        """
                        INSERT INTO classify_overrides (unit_key, category, name, creator, tags,
                                                        note)
                        VALUES (:k, :c, :n, :cr, :t, :note)
                        ON CONFLICT (unit_key) DO UPDATE SET
                            category = coalesce(EXCLUDED.category, classify_overrides.category),
                            name = coalesce(EXCLUDED.name, classify_overrides.name),
                            creator = coalesce(EXCLUDED.creator, classify_overrides.creator),
                            tags = coalesce(EXCLUDED.tags, classify_overrides.tags),
                            note = coalesce(EXCLUDED.note, classify_overrides.note),
                            created_at = now()
                        """
                    ),
                    {
                        "k": key,
                        "c": cat,
                        "n": name,
                        "cr": creator,
                        "t": tag_list,
                        "note": (row.get("note") or "").strip() or None,
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
    n: int = 50, *, seed: int = 32, db_url: str | None = None, out: TextIO = sys.stdout
) -> int:
    """Print n random classified packs (JSONL) with the evidence behind each classification."""
    engine = _engine(db_url)
    try:
        with engine.connect() as conn:
            rows = _pack_rows(conn, "p.category IS NOT NULL")
            picked = random.Random(seed).sample(rows, min(n, len(rows)))
            for i, r in enumerate(picked, start=1):
                pid, cat, name, creator, source, tags, reasons, by, conf, fp, unit_key, paths = r
                ev = conn.execute(
                    text(
                        """
                        SELECT evidence FROM classify_decisions WHERE input_fingerprint = :fp
                        ORDER BY id DESC LIMIT 1
                        """
                    ),
                    {"fp": fp},
                ).scalar()
                out.write(
                    json.dumps(
                        {
                            "n": i,
                            "pack_id": pid,
                            "category": cat,
                            "name": name,
                            "creator": creator,
                            "source_tag": source,
                            "tags": list(tags or [])[:15],
                            "decided_by": by,
                            "confidence": float(conf) if conf is not None else None,
                            "review_reasons": list(reasons or []),
                            "unit_key": unit_key,
                            "paths": list(paths or []),
                            "evidence": ev,
                        },
                        ensure_ascii=False,
                        default=str,
                    )
                    + "\n"
                )
    finally:
        engine.dispose()
    return len(picked)
