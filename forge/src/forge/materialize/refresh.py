"""``forge materialize refresh-datapackage`` — rewrite ONLY ``datapackage.json`` of packs that are
already materialized, so tags decided after the plan (``forge tags``) reach Manyfold.

For every pack of the plan with status ``done`` / ``incomplete`` the pack's ``keywords`` are rebuilt
from the live ``packs`` row (:func:`forge.materialize.keywords.pack_keywords`); everything else in
the file (resources, hashes, provenance, ``forge.*``) is left byte-for-byte as it was. A file is
rewritten only when its keywords differ, via a new temp name + ``rename()`` through the write
guard (atomic; the old name's inode is never opened for write). Nothing else is written: no
pack file is created, moved or deleted, a pack directory or ``datapackage.json`` that is missing is
reported and skipped (never created), and the source tree (3D-Prints) is unreachable — every path
is resolved by :class:`forge.materialize.guard.WriteGuard`, which refuses anything outside v2.

The plan's stored ``materialize_packs.meta`` is updated to match, so a later ``apply`` of the same
plan writes the same keywords.

INIT-032/SPEC-016
"""

from __future__ import annotations

import json
import os
from collections import Counter

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .guard import WriteGuard, join_v2
from .keywords import pack_keywords
from .paths import DATAPACKAGE
from .store import TempWriter

MAX_READ = 64 << 20  # a datapackage lists every file; 64 MiB is far above any real pack

_SELECT = """
SELECT m.pack_id, m.dir, m.category, m.meta, p.source_tag, p.creator, p.tags,
       p.tags_fingerprint IS NOT NULL AS tagged
FROM materialize_packs m JOIN packs p ON p.id = m.pack_id
WHERE m.plan_id = :plan AND m.status IN ('done', 'incomplete')
  AND (CAST(:ids AS bigint[]) IS NULL OR m.pack_id = ANY(CAST(:ids AS bigint[])))
ORDER BY m.pack_id
LIMIT CAST(:lim AS bigint)
"""


def _read_json(path: str) -> dict | None:
    """The parsed object, ``None`` when the file is absent; ValueError for anything else."""
    try:
        fd = WriteGuard.open_read(path)
    except FileNotFoundError:
        return None
    except OSError as exc:  # symlink (ELOOP), permission, ...
        raise ValueError(f"cannot open: {exc.strerror}") from exc
    try:
        chunks, total = [], 0
        while True:
            data = os.read(fd, 1 << 20)
            if not data:
                break
            total += len(data)
            if total > MAX_READ:
                raise ValueError("file too large")
            chunks.append(data)
    finally:
        os.close(fd)
    obj = json.loads(b"".join(chunks))
    if not isinstance(obj, dict):
        raise ValueError("not a JSON object")
    return obj


def _write_json(guard: WriteGuard, path, obj: dict) -> None:
    body = (json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    tmp = guard.new_temp_name(os.path.dirname(path), ".forge-tmp-")
    w = TempWriter(guard, tmp)
    try:
        w.write(body)
        w.close()
    except BaseException:
        w.abort()
        raise
    guard.rename(tmp, path)


def refresh_datapackages(
    engine: Engine,
    plan_id: int,
    guard: WriteGuard,
    *,
    pack_ids: list[int] | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict:
    counts: Counter[str] = Counter(
        {"updated": 0, "unchanged": 0, "missing_datapackage": 0, "unreadable": 0}
    )
    changed: list[str] = []
    with engine.connect() as conn:
        rows = conn.execute(
            text(_SELECT), {"plan": plan_id, "ids": pack_ids or None, "lim": limit}
        ).mappings()
        packs = [dict(r) for r in rows]
    counts["packs"] = len(packs)
    if pack_ids:
        counts["not_in_plan"] = len(set(pack_ids) - {int(p["pack_id"]) for p in packs})
    meta_updates = []
    for p in packs:
        path = str(join_v2(guard, p["dir"]) / DATAPACKAGE)  # GuardError on a hostile plan path
        try:
            old = _read_json(path)
        except ValueError:
            counts["unreadable"] += 1
            continue
        if old is None:
            counts["missing_datapackage"] += 1
            continue
        keywords = pack_keywords(
            category=p["category"],
            source_tag=p["source_tag"],
            creator=p["creator"],
            tags=p["tags"],
            tagged=bool(p["tagged"]),
        )
        meta = json.loads(p["meta"] or "{}")
        want_meta = {
            **meta,
            "creator": p["creator"],
            "source_tag": p["source_tag"],
            "tags": list(p["tags"] or []),
            "tagged": bool(p["tagged"]),
        }
        if want_meta != meta:
            meta_updates.append({"p": plan_id, "id": p["pack_id"], "m": want_meta})
        if old.get("keywords") == keywords:
            counts["unchanged"] += 1
            continue
        counts["would_update" if dry_run else "updated"] += 1
        if len(changed) < 20:
            changed.append(p["dir"])
        if not dry_run:
            _write_json(guard, path, {**old, "keywords": keywords})
    if meta_updates and not dry_run:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE materialize_packs SET meta = :m WHERE plan_id = :p AND pack_id = :id"),
                [
                    {"p": u["p"], "id": u["id"], "m": json.dumps(u["m"], sort_keys=True)}
                    for u in meta_updates
                ],
            )
    counts["plan_meta_synced"] = len(meta_updates) if not dry_run else 0
    return {"plan": plan_id, "dry_run": dry_run, **dict(sorted(counts.items())), "sample": changed}
