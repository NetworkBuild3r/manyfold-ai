"""``forge requeue``: put failed containers back in the queue (INIT-032/SPEC-007).

Two uses:

* a second pass for cap failures (``spool_exceeded`` / ``oom`` / ``member_too_large`` ...) with
  bigger caps in the environment of the sweep that then runs (``FORGE_CAP_SPOOL_BYTES`` ...). A
  nested failure is retried through its root archive: the root is ``done`` and the nested child
  is only re-read when the root is read again.
* any failure after the engine/walker was fixed (e.g. ``reader_error`` on volumes that are now
  resolved as one set — normally ``forge walk`` already re-queues those itself).

Reset = what the walker does when a container's files change: occurrences and nested children
are purged, the container goes back to ``pending`` with ``attempts = 0``. Source files, pack
rows and everything else are left alone. Never touches the source tree.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Connection

from forge.config import ConfigError, ForgeConfig

_ROOTS = text(
    """
    WITH RECURSIVE f(id, parent_id) AS (
        SELECT id, parent_container_id FROM containers
        WHERE status = 'failed' AND failure_reason::text = ANY(CAST(:reasons AS text[]))
          AND superseded_by_id IS NULL
        UNION
        SELECT c.id, c.parent_container_id FROM containers c JOIN f ON c.id = f.parent_id
    )
    SELECT c.id, c.format, coalesce(c.source_file_id, 0) AS sfid,
           (SELECT coalesce(sum(sf.size), 0) FROM container_files cf
            JOIN source_files sf ON sf.id = cf.source_file_id
            WHERE cf.container_id = c.id) AS bytes,
           (SELECT sf.path FROM container_files cf JOIN source_files sf
            ON sf.id = cf.source_file_id WHERE cf.container_id = c.id AND cf.ordinal = 1) AS path
    FROM containers c
    WHERE c.id IN (SELECT id FROM f) AND c.parent_container_id IS NULL AND c.kind = 'archive'
      AND c.status <> 'claimed'
    ORDER BY bytes, c.id
    """
)


@dataclass
class RequeueResult:
    reasons: tuple[str, ...]
    selected: int = 0
    source_bytes: int = 0
    skipped_too_big: int = 0
    ids: list[int] = field(default_factory=list)
    dry_run: bool = False


def requeue(
    conn: Connection,
    reasons: tuple[str, ...],
    *,
    max_source_bytes: int | None = None,
    only_ids: tuple[int, ...] = (),
    limit: int | None = None,
    dry_run: bool = False,
) -> RequeueResult:
    from forge.walker import _reset_container

    result = RequeueResult(tuple(reasons), dry_run=dry_run)
    rows = conn.execute(_ROOTS, {"reasons": list(reasons)}).mappings().all()
    for row in rows:
        if only_ids and row["id"] not in only_ids:
            continue
        if max_source_bytes is not None and row["bytes"] > max_source_bytes:
            result.skipped_too_big += 1
            continue
        if limit is not None and result.selected >= limit:
            break
        result.selected += 1
        result.source_bytes += int(row["bytes"])
        result.ids.append(int(row["id"]))
        if dry_run:
            continue
        _reset_container(
            conn,
            int(row["id"]),
            status="pending",
            failure=None,
            source_file_id=int(row["sfid"]) or None,
            fmt=row["format"],
            notes=json.dumps({"requeued_for": list(reasons)}, separators=(",", ":")),
        )
    return result


def main_requeue(args) -> int:
    from forge.db.session import get_engine

    reasons = tuple(args.reason or ())
    if not reasons:
        print("forge requeue: pass at least one --reason", file=sys.stderr)
        return 2
    try:
        engine = get_engine(ForgeConfig.from_env().require_db_url())
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    with engine.begin() as conn:
        res = requeue(
            conn,
            reasons,
            max_source_bytes=args.max_source_bytes,
            only_ids=tuple(args.id or ()),
            limit=args.limit,
            dry_run=args.dry_run,
        )
    verb = "would requeue" if res.dry_run else "requeued"
    print(
        f"{verb} {res.selected} top-level containers "
        f"({res.source_bytes / 1e9:.1f} GB on the NAS) for {', '.join(reasons)}; "
        f"{res.skipped_too_big} skipped over --max-source-bytes"
    )
    return 0
