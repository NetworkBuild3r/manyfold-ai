"""Human review loop for pack resolution: review CSV export, override CSV import, audit sample.

Override rows land in pack_decisions as kind='human' keyed by unit keys, so they survive unit /
pack id changes; the latest human row per unit pair wins over every other tier on the next run.

INIT-032/SPEC-010
"""

from __future__ import annotations

import csv
import json
import random
import sys
from collections.abc import Iterable
from typing import TextIO

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from forge.config import require_db_url

REVIEW_COLUMNS = (
    "key_a",
    "key_b",
    "llm_verdict",
    "confidence",
    "reason",
    "error",
    "shared_meshes",
    "unique_a",
    "unique_b",
    "containment_count",
    "paths_a",
    "paths_b",
    "verdict",
    "note",
)
HUMAN_VERDICTS = ("same_pack", "separate")


class OverrideError(ValueError):
    pass


def _engine(db_url: str | None):
    return create_engine(db_url or require_db_url(), pool_pre_ping=True)


def resolve_key(conn: Connection, ref: str) -> str:
    """Accept a unit key (archive:/loose:), an archive path, or a loose folder path."""
    ref = ref.strip()
    if ref.startswith(("archive:", "loose:")):
        return ref
    row = conn.execute(
        text(
            """
            SELECT unit_key FROM pack_units
            WHERE present AND unit_key IN (:a, :l) ORDER BY kind LIMIT 1
            """
        ),
        {"a": "archive:" + ref, "l": "loose:" + ref},
    ).first()
    if row is None:
        raise OverrideError(f"no unit for {ref!r} (use archive:<path> or loose:<folder>)")
    return row[0]


def import_overrides(rows: Iterable[dict], *, db_url: str | None = None) -> dict[str, int]:
    """Insert kind='human' decisions (columns key_a|a, key_b|b, verdict, note; blank skips)."""
    counts = {"imported": 0, "skipped_blank": 0}
    engine = _engine(db_url)
    try:
        with engine.begin() as conn:
            for i, row in enumerate(rows, start=2):
                verdict = (row.get("verdict") or "").strip()
                if not verdict:
                    counts["skipped_blank"] += 1
                    continue
                if verdict not in HUMAN_VERDICTS:
                    raise OverrideError(f"line {i}: verdict must be same_pack|separate")
                a = row.get("key_a") or row.get("a") or ""
                b = row.get("key_b") or row.get("b") or ""
                if not a.strip() or not b.strip():
                    raise OverrideError(f"line {i}: both sides are required")
                ka, kb = sorted((resolve_key(conn, a), resolve_key(conn, b)))
                if ka == kb:
                    raise OverrideError(f"line {i}: both sides are the same unit")
                ids = dict(
                    conn.execute(
                        text("SELECT unit_key, id FROM pack_units WHERE unit_key IN (:a, :b)"),
                        {"a": ka, "b": kb},
                    ).all()
                )
                roots = dict(
                    conn.execute(
                        text(
                            "SELECT unit_key, root_container_id FROM pack_units "
                            "WHERE unit_key IN (:a, :b)"
                        ),
                        {"a": ka, "b": kb},
                    ).all()
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO pack_decisions (kind, container_a, container_b, unit_a, unit_b,
                            key_a, key_b, verdict, confidence, rationale, human_override)
                        VALUES ('human', :ca, :cb, :ua, :ub, :ka, :kb,
                            CAST(:v AS pack_verdict), 1, :note, true)
                        """
                    ),
                    {
                        "ca": roots.get(ka),
                        "cb": roots.get(kb),
                        "ua": ids.get(ka),
                        "ub": ids.get(kb),
                        "ka": ka,
                        "kb": kb,
                        "v": verdict,
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


def _paths(evidence: dict | None, side: str) -> str:
    if not evidence:
        return ""
    return " | ".join(evidence.get(side, {}).get("paths", []))


def export_review(out: TextIO, *, db_url: str | None = None) -> int:
    """Latest needs_review LLM decisions with no later human decision for the same pair."""
    engine = _engine(db_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT d.key_a, d.key_b, d.verdict::text, d.confidence, d.rationale, d.error,
                           d.evidence
                    FROM pack_decisions d
                    WHERE d.kind = 'llm' AND d.needs_review
                      AND d.id = (SELECT max(x.id) FROM pack_decisions x
                                  WHERE x.kind = 'llm' AND x.key_a = d.key_a
                                    AND x.key_b = d.key_b)
                      AND NOT EXISTS (
                          SELECT 1 FROM pack_decisions h
                          WHERE h.kind = 'human' AND h.id > d.id
                            AND least(h.key_a, h.key_b) = least(d.key_a, d.key_b)
                            AND greatest(h.key_a, h.key_b) = greatest(d.key_a, d.key_b))
                    ORDER BY d.id
                    """
                )
            ).all()
    finally:
        engine.dispose()
    writer = csv.DictWriter(out, fieldnames=REVIEW_COLUMNS)
    writer.writeheader()
    for ka, kb, verdict, conf, reason, error, ev in rows:
        ev = ev or {}
        writer.writerow(
            {
                "key_a": ka,
                "key_b": kb,
                "llm_verdict": verdict,
                "confidence": conf,
                "reason": reason,
                "error": error,
                "shared_meshes": ev.get("shared", {}).get("meshes"),
                "unique_a": ev.get("a", {}).get("unique_meshes"),
                "unique_b": ev.get("b", {}).get("unique_meshes"),
                "containment_count": ev.get("containment_count"),
                "paths_a": _paths(ev, "a"),
                "paths_b": _paths(ev, "b"),
                "verdict": "",
                "note": "",
            }
        )
    return len(rows)


def sample(
    n: int = 40, *, seed: int = 32, db_url: str | None = None, out: TextIO = sys.stdout
) -> int:
    """Print n random current LLM decisions with their evidence for a human / judge audit."""
    engine = _engine(db_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT DISTINCT ON (input_fingerprint) id, key_a, key_b, verdict::text,
                           confidence, rationale, error, model, evidence
                    FROM pack_decisions
                    WHERE kind = 'llm'
                    ORDER BY input_fingerprint, id DESC
                    """
                )
            ).all()
    finally:
        engine.dispose()
    rows = sorted(rows, key=lambda r: r[0])
    picked = random.Random(seed).sample(rows, min(n, len(rows)))
    for i, (did, ka, kb, verdict, conf, reason, error, model, ev) in enumerate(picked, start=1):
        out.write(
            json.dumps(
                {
                    "n": i,
                    "decision_id": did,
                    "verdict": verdict,
                    "confidence": float(conf) if conf is not None else None,
                    "reason": reason,
                    "error": error,
                    "model": model,
                    "key_a": ka,
                    "key_b": kb,
                    "evidence": ev,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return len(picked)
