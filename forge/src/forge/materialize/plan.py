"""``forge materialize plan`` — decide the v2 tree from the catalog. Pure DB (no NAS reads).

For each selected pack: the file list is the union of the mesh/image/doc blobs found in its
``pack_containers`` (each container including its nested descendants) and the loose files named by
its loose ``pack_units`` / ``pack_unit_sources`` (split ``loose_batch`` containers), deduplicated
by blob.
The path of a file is ``<Category>/<Pack>/<relative path inside source>`` where the relative
path is taken from the pack's best occurrence of that blob (role primary > source > absorbed,
then shallowest, then path). For each needed blob ONE source is chosen globally:

* ``loose``   — a present loose source file of the right size (hardlinked, zero bytes copied);
* ``archive`` — a member of a top-level archive (extracted once; prefer containers that finished
  ``done``, then the shallowest member, then the smallest container);
* ``missing`` — no readable source (shortage; reported, never invented).

Work units for ``apply``: one per source archive (all its needed members in one pass) and loose
blobs in chunks. Plans are append-only; a new plan supersedes the previous active one.
"""

from __future__ import annotations

import json
import os
import posixpath
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from forge import __version__

from .paths import (
    Candidate,
    category_dir,
    chain_components,
    is_junk,
    pack_folder_name,
    resolve_collisions,
    sanitize_component,
    sanitize_components,
    strip_archive_suffix,
)

KINDS = ("mesh", "image", "doc")
ROLE_PRIORITY = {"primary": 0, "source": 1, "absorbed": 2}
LOOSE_UNIT_MAX_BLOBS = 2000
SCOPE_BATCH = 10_000
DEFAULT_PACK_STATUSES = ("resolved", "materialized")


class PlanError(RuntimeError):
    pass


@dataclass
class PlanOptions:
    layout: str = "tree"  # tree | flat
    include_provisional: bool = False
    pack_ids: list[int] | None = None
    free_bytes: int | None = None
    force: bool = False


@dataclass
class PlannedFile:
    rel_path: str
    sha: str
    size: int
    kind: str
    container_id: int
    anchor_path: str
    member_chain: list[str]


@dataclass
class PlannedPack:
    pack_id: int
    category: str
    name: str | None
    dir: str
    files: list[PlannedFile] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


@dataclass
class PlanResult:
    plan_id: int
    totals: dict
    packs: list[PlannedPack]
    blobs: dict[str, dict]


# --------------------------------------------------------------------------------------- SQL

_ROOTS = """
CREATE TEMP TABLE mat_roots ON COMMIT DROP AS
WITH RECURSIVE r(id, root_id) AS (
    SELECT id, id FROM containers WHERE parent_container_id IS NULL
    UNION ALL
    SELECT c.id, r.root_id FROM containers c JOIN r ON c.parent_container_id = r.id
)
SELECT id, root_id FROM r;
CREATE INDEX ON mat_roots (id);
ANALYZE mat_roots;
"""

_PACKS = """
SELECT id, name, category, creator, source_tag, status::text AS status, needs_review,
       tags, tags_fingerprint IS NOT NULL AS tagged
FROM packs
WHERE status::text = ANY(CAST(:statuses AS text[]))
  AND (CAST(:ids AS bigint[]) IS NULL OR id = ANY(CAST(:ids AS bigint[])))
ORDER BY id
"""

_PACK_CONTAINERS = """
SELECT pc.pack_id, pc.container_id, pc.role::text AS role, c.kind::text AS kind
FROM pack_containers pc JOIN containers c ON c.id = pc.container_id
WHERE pc.pack_id = ANY(CAST(:packs AS bigint[]))
ORDER BY pc.pack_id, pc.container_id
"""

# Second branch of _SCOPE: loose members of split loose_batch containers. pack_unit_sources names
# the exact source files of each loose unit and the unit's pack_id/role say where they go. The
# batch container itself is never attached to the pack, so a batch already in pack_containers for
# the same pack is skipped (no double planning; those files arrive through the first branch with
# the container's role). Units with pack_id NULL never match (they are reported separately).
_SCOPE = """
WITH RECURSIVE s(pack_id, role, cid) AS (
    SELECT pc.pack_id, pc.role::text, pc.container_id
    FROM pack_containers pc WHERE pc.pack_id = ANY(CAST(:packs AS bigint[]))
    UNION
    SELECT s.pack_id, s.role, c.id FROM containers c JOIN s ON c.parent_container_id = s.cid
)
SELECT s.pack_id, s.role, o.blob_sha, b.size, b.kind::text AS kind, o.container_id,
       o.member_chain, o.member_path, o.depth, r.root_id
FROM s
JOIN occurrences o ON o.container_id = s.cid
JOIN blobs b ON b.sha256 = o.blob_sha
JOIN mat_roots r ON r.id = o.container_id
WHERE b.kind::text = ANY(CAST(:kinds AS text[]))
UNION ALL
SELECT pu.pack_id, pu.role::text, o.blob_sha, b.size, b.kind::text, o.container_id,
       o.member_chain, o.member_path, o.depth, r.root_id
FROM pack_units pu
JOIN pack_unit_sources pus ON pus.unit_id = pu.id
JOIN source_files sf ON sf.id = pus.source_file_id
JOIN occurrences o ON o.member_chain[1] = sf.path AND cardinality(o.member_chain) = 1
JOIN containers c ON c.id = o.container_id AND c.kind = 'loose_batch'
JOIN blobs b ON b.sha256 = o.blob_sha
JOIN mat_roots r ON r.id = o.container_id
WHERE pu.pack_id = ANY(CAST(:packs AS bigint[]))
  AND pu.kind = 'loose' AND pu.present AND pu.role IS NOT NULL
  AND b.kind::text = ANY(CAST(:kinds AS text[]))
  AND NOT EXISTS (
      SELECT 1 FROM pack_containers pc
      WHERE pc.pack_id = pu.pack_id AND pc.container_id = o.container_id
  )
ORDER BY pack_id
"""

# Loose units that no pack claimed (pack_id NULL): their files stay out of every pack. Reported,
# never guessed into a pack.
_UNASSIGNED_UNITS = """
SELECT pu.id, pu.unit_key, pu.role::text AS role,
       (SELECT count(*) FROM pack_unit_sources pus WHERE pus.unit_id = pu.id) AS files
FROM pack_units pu
WHERE pu.kind = 'loose' AND pu.present AND pu.pack_id IS NULL
  AND EXISTS (SELECT 1 FROM pack_unit_sources pus WHERE pus.unit_id = pu.id)
ORDER BY pu.id
"""

_PACK_UNITS = """
SELECT pu.pack_id, pu.id AS unit_id, pu.unit_key, pu.path, pu.role::text AS role
FROM pack_units pu
WHERE pu.pack_id = ANY(CAST(:packs AS bigint[]))
  AND pu.kind = 'loose' AND pu.present AND pu.role IS NOT NULL
  AND EXISTS (SELECT 1 FROM pack_unit_sources pus WHERE pus.unit_id = pu.id)
ORDER BY pu.pack_id, pu.id
"""

_ROOT_INFO = """
SELECT c.id, c.kind::text AS kind, c.status::text AS status,
       COALESCE(c.source_bytes, 0) AS source_bytes, sf.path AS first_path
FROM containers c
LEFT JOIN container_files cf ON cf.container_id = c.id AND cf.ordinal = 1
LEFT JOIN source_files sf ON sf.id = cf.source_file_id
WHERE c.parent_container_id IS NULL
"""

_ROOT_PATHS = """
SELECT cf.container_id, sf.path, sf.size
FROM container_files cf JOIN source_files sf ON sf.id = cf.source_file_id
WHERE cf.container_id = ANY(CAST(:ids AS bigint[]))
ORDER BY cf.container_id, cf.ordinal
"""

_LOOSE_SOURCES = """
SELECT DISTINCT ON (n.sha) n.sha, sf.path, sf.size, sf.mtime
FROM mat_need n
JOIN occurrences o ON o.blob_sha = n.sha AND cardinality(o.member_chain) = 1
JOIN containers c ON c.id = o.container_id AND c.kind = 'loose_batch'
JOIN source_files sf ON sf.path = o.member_chain[1] AND sf.present AND sf.size = n.size
ORDER BY n.sha, sf.path
"""

_ARCHIVE_SOURCES = """
SELECT DISTINCT ON (n.sha) n.sha, r.root_id, o.member_chain, rc.status::text AS root_status,
       COALESCE(rc.source_bytes, 0) AS source_bytes
FROM mat_need n
JOIN occurrences o ON o.blob_sha = n.sha
JOIN mat_roots r ON r.id = o.container_id
JOIN containers rc ON rc.id = r.root_id AND rc.kind = 'archive'
WHERE NOT n.loose
  AND NOT EXISTS (
      SELECT 1 FROM container_files cf JOIN source_files sf ON sf.id = cf.source_file_id
      WHERE cf.container_id = rc.id AND NOT sf.present
  )
ORDER BY n.sha, (rc.status = 'done') DESC, o.depth, rc.source_bytes NULLS LAST, rc.id,
         o.member_path
"""


def _arr(values) -> list:
    return list(values)


# ------------------------------------------------------------------------------------- build


def _choose_occurrence(rows: list) -> dict | None:
    best = None
    best_key = None
    for r in rows:
        comps = chain_components(r["member_chain"])
        if is_junk(comps):
            continue
        key = (ROLE_PRIORITY.get(r["role"], 9), r["depth"], r["member_path"], r["container_id"])
        if best_key is None or key < best_key:
            best, best_key = r, key
    return best


def _layout_pack(
    pack_rows: list,
    roots: dict[int, dict],
    layout: str,
    pack_dir: str,
    junk: Counter,
) -> list[PlannedFile]:
    by_sha: dict[str, list] = defaultdict(list)
    for r in pack_rows:
        by_sha[r["blob_sha"]].append(r)
    chosen: list[dict] = []
    for sha in sorted(by_sha):
        occ = _choose_occurrence(by_sha[sha])
        if occ is None:
            junk["blobs"] += 1
            continue
        chosen.append(occ)
    if not chosen:
        return []

    def anchor(r: dict) -> str:
        root = roots[r["root_id"]]
        if root["kind"] == "loose_batch":
            return r["member_chain"][0]
        return root["first_path"] or f"container-{r['root_id']}"

    anchors = {id(r): anchor(r) for r in chosen}
    dirs = [posixpath.dirname(a) for a in anchors.values()]
    try:
        base = posixpath.commonpath(dirs) if all(dirs) else ""
    except ValueError:
        base = ""
    archive_roots = {r["root_id"] for r in chosen if roots[r["root_id"]]["kind"] != "loose_batch"}
    multi_archive = len(archive_roots) > 1

    cands: list[tuple[tuple, Candidate, dict]] = []
    for r in chosen:
        a = anchors[id(r)]
        is_loose = roots[r["root_id"]]["kind"] == "loose_batch"
        if is_loose:
            comps = posixpath.relpath(a, base or ".").split("/")
        else:
            d = posixpath.relpath(posixpath.dirname(a) or ".", base or ".")
            comps = [p for p in d.split("/") if p not in ("", ".")]
            if multi_archive:
                comps.append(strip_archive_suffix(posixpath.basename(a)))
            comps += chain_components(r["member_chain"])
        if layout == "flat":
            comps = comps[-1:]
        rel = "/".join(sanitize_components(comps))
        prio = (ROLE_PRIORITY.get(r["role"], 9), r["depth"], rel, r["blob_sha"])
        cands.append((prio, Candidate(rel, r["blob_sha"]), r | {"anchor": a}))
    cands.sort(key=lambda t: t[0])
    final = resolve_collisions([c for _, c, _ in cands], pack_dir)
    out = []
    for _, c, r in cands:
        out.append(
            PlannedFile(
                rel_path=final[c.sha],
                sha=c.sha,
                size=int(r["size"]),
                kind=r["kind"],
                container_id=int(r["container_id"]),
                anchor_path=r["anchor"],
                member_chain=list(r["member_chain"]),
            )
        )
    out.sort(key=lambda f: f.rel_path)
    return out


def _dir_key(d: str) -> str:
    return d.casefold()


def compute(conn: Connection, opts: PlanOptions) -> tuple[list[PlannedPack], dict, dict]:
    """Return (packs, blobs, totals) without writing anything."""
    if opts.layout not in ("tree", "flat"):
        raise PlanError(f"unknown layout {opts.layout!r}")
    statuses = list(DEFAULT_PACK_STATUSES) + (["provisional"] if opts.include_provisional else [])
    for stmt in _ROOTS.strip().split(";"):
        if stmt.strip():
            conn.execute(text(stmt))
    packs = (
        conn.execute(text(_PACKS), {"statuses": statuses, "ids": opts.pack_ids}).mappings().all()
    )
    pack_ids = [int(p["id"]) for p in packs]
    pcs = conn.execute(text(_PACK_CONTAINERS), {"packs": pack_ids}).mappings().all()
    pcs_by_pack: dict[int, list] = defaultdict(list)
    for pc in pcs:
        pcs_by_pack[int(pc["pack_id"])].append(dict(pc))
    units_by_pack: dict[int, list[dict]] = defaultdict(list)
    for u in conn.execute(text(_PACK_UNITS), {"packs": pack_ids}).mappings():
        units_by_pack[int(u["pack_id"])].append(
            {
                "unit_id": int(u["unit_id"]),
                "unit_key": u["unit_key"],
                "path": u["path"],
                "role": u["role"],
            }
        )
    unassigned = [dict(u) for u in conn.execute(text(_UNASSIGNED_UNITS)).mappings()]
    roots = {int(r["id"]): dict(r) for r in conn.execute(text(_ROOT_INFO)).mappings()}
    root_paths: dict[int, list[str]] = defaultdict(list)
    pc_ids = sorted({int(pc["container_id"]) for pc in pcs})
    for r in conn.execute(text(_ROOT_PATHS), {"ids": pc_ids}).mappings():
        root_paths[int(r["container_id"])].append(r["path"])

    # Stream occurrences pack by pack (ORDER BY pack_id) so only one pack's rows are in memory.
    by_id = {int(p["id"]): p for p in packs}
    junk: Counter = Counter()
    files_by_pack: dict[int, list[PlannedFile]] = {}

    def lay_out(pid: int, rows: list) -> None:
        p = by_id[pid]
        # Budget long paths against the longest folder name this pack can get.
        worst = f"{category_dir(p['category'])}/{pack_folder_name(p['name'], pid)} [{pid}]"
        files_by_pack[pid] = _layout_pack(rows, roots, opts.layout, worst, junk)

    stmt = text(_SCOPE).execution_options(stream_results=True, yield_per=SCOPE_BATCH)
    cur_pid: int | None = None
    cur_rows: list = []
    for r in conn.execute(stmt, {"packs": pack_ids, "kinds": list(KINDS)}).mappings():
        pid = int(r["pack_id"])
        if pid != cur_pid:
            if cur_pid is not None:
                lay_out(cur_pid, cur_rows)
            cur_pid, cur_rows = pid, []
        d = dict(r)
        d["member_chain"] = list(d["member_chain"])
        cur_rows.append(d)
    if cur_pid is not None:
        lay_out(cur_pid, cur_rows)

    planned: list[PlannedPack] = []
    taken_dirs: set[str] = set()
    empty_packs = 0
    uncategorized = 0
    for p in packs:
        pid = int(p["id"])
        cat = category_dir(p["category"])
        if p["category"] is None:
            uncategorized += 1
        folder = pack_folder_name(p["name"], pid)
        pdir = f"{cat}/{folder}"
        if _dir_key(pdir) in taken_dirs:
            folder = sanitize_component(f"{folder} [{pid}]")
            pdir = f"{cat}/{folder}"
        files = files_by_pack.pop(pid, [])
        if not files:
            empty_packs += 1
            continue
        taken_dirs.add(_dir_key(pdir))
        containers_meta = []
        for pc in pcs_by_pack.get(pid, []):
            cid = int(pc["container_id"])
            if pc["kind"] == "loose_batch":
                paths = sorted(
                    {
                        f.anchor_path
                        for f in files
                        if f.member_chain[0] == f.anchor_path and f.container_id == cid
                    }
                )
            else:
                paths = root_paths.get(cid, [])
            containers_meta.append(
                {"container_id": cid, "role": pc["role"], "kind": pc["kind"], "paths": paths}
            )
        planned.append(
            PlannedPack(
                pack_id=pid,
                category=cat,
                name=p["name"],
                dir=pdir,
                files=files,
                meta={
                    "creator": p["creator"],
                    "source_tag": p["source_tag"],
                    "tags": list(p["tags"] or []),
                    "tagged": bool(p["tagged"]),
                    "needs_review": bool(p["needs_review"]),
                    "pack_status": p["status"],
                    "classified": p["category"] is not None,
                    "containers": containers_meta,
                    "loose_units": units_by_pack.get(pid, []),
                },
            )
        )

    need: dict[str, dict] = {}
    for pk in planned:
        for f in pk.files:
            need.setdefault(f.sha, {"sha256": f.sha, "size": f.size, "kind": f.kind})
    conn.execute(
        text(
            "CREATE TEMP TABLE mat_need (sha text PRIMARY KEY, size bigint, loose bool) "
            "ON COMMIT DROP"
        )
    )
    if need:
        conn.execute(
            text("INSERT INTO mat_need (sha, size, loose) VALUES (:sha, :size, false)"),
            [{"sha": s, "size": b["size"]} for s, b in need.items()],
        )
    conn.execute(text("ANALYZE mat_need"))
    for r in conn.execute(text(_LOOSE_SOURCES)).mappings():
        b = need[r["sha"]]
        b.update(
            source_kind="loose",
            source_path=r["path"],
            source_size=int(r["size"]),
            source_mtime=r["mtime"],
        )
    conn.execute(
        text("UPDATE mat_need SET loose = true WHERE sha = ANY(CAST(:s AS text[]))"),
        {"s": [s for s, b in need.items() if b.get("source_kind") == "loose"]},
    )
    for r in conn.execute(text(_ARCHIVE_SOURCES)).mappings():
        b = need[r["sha"]]
        b.update(
            source_kind="archive",
            root_container_id=int(r["root_id"]),
            member_chain=list(r["member_chain"]),
            root_status=r["root_status"],
            root_source_bytes=int(r["source_bytes"]),
        )
    for b in need.values():
        b.setdefault("source_kind", "missing")

    totals = _totals(planned, need, junk, empty_packs, uncategorized, opts, unassigned)
    return planned, need, totals


def _totals(planned, need, junk, empty_packs, uncategorized, opts, unassigned=()) -> dict:
    by_kind = Counter()
    by_kind_bytes = Counter()
    for b in need.values():
        by_kind[b["source_kind"]] += 1
        by_kind_bytes[b["source_kind"]] += b["size"]
    roots = {
        b["root_container_id"]: b["root_source_bytes"]
        for b in need.values()
        if b["source_kind"] == "archive"
    }
    files = sum(len(p.files) for p in planned)
    linked = sum(f.size for p in planned for f in p.files)
    unique = sum(b["size"] for b in need.values())
    # New bytes written to the NAS: extracted blobs (+ loose copies only if hardlinks fail).
    write_bytes = by_kind_bytes["archive"]
    t = {
        "tool_version": __version__,
        "layout": opts.layout,
        "packs": len(planned),
        "empty_packs_skipped": empty_packs,
        "uncategorized_packs_in_misc": uncategorized,
        "needs_review_packs": sum(1 for p in planned if p.meta.get("needs_review")),
        "files": files,
        "blobs": len(need),
        "unique_bytes": unique,
        "linked_bytes": linked,
        "dedup_saved_bytes": linked - unique,
        "loose_blobs": by_kind["loose"],
        "loose_bytes": by_kind_bytes["loose"],
        "archive_blobs": by_kind["archive"],
        "archive_bytes": by_kind_bytes["archive"],
        "missing_blobs": by_kind["missing"],
        "missing_bytes": by_kind_bytes["missing"],
        "archive_units": len(roots),
        "archive_source_bytes_to_read": sum(roots.values()),
        "junk_blobs_skipped": junk["blobs"],
        # Loose units no pack claimed (pack_id NULL): skipped, never guessed into a pack.
        "unassigned_loose_units": len(unassigned),
        "unassigned_loose_files": sum(int(u["files"]) for u in unassigned),
        "unassigned_loose_unit_sample": [u["unit_key"] for u in unassigned[:20]],
        "write_bytes_hardlink_mode": write_bytes,
        "write_bytes_copy_mode": unique + linked,
        "free_bytes": opts.free_bytes,
    }
    if opts.free_bytes is not None:
        t["fits_hardlink_mode"] = opts.free_bytes > write_bytes * 1.05
        t["fits_copy_mode"] = opts.free_bytes > (unique + linked) * 1.05
    return t


# ------------------------------------------------------------------------------------- write


def _active_claims(conn: Connection) -> int:
    return int(
        conn.execute(
            text(
                """
                SELECT (SELECT count(*) FROM materialize_units u
                        JOIN materialize_plans p ON p.id = u.plan_id
                        WHERE p.status = 'active' AND u.status = 'claimed')
                     + (SELECT count(*) FROM materialize_packs k
                        JOIN materialize_plans p ON p.id = k.plan_id
                        WHERE p.status = 'active' AND k.status = 'claimed')
                """
            )
        ).scalar_one()
    )


def build_plan(engine: Engine, opts: PlanOptions) -> PlanResult:
    with engine.begin() as conn:
        if not opts.force and _active_claims(conn):
            raise PlanError(
                "an apply is in progress on the active plan (claimed units/packs); "
                "wait for it or pass --force"
            )
        planned, need, totals = compute(conn, opts)
        conn.execute(
            text("UPDATE materialize_plans SET status = 'superseded' WHERE status = 'active'")
        )
        plan_id = int(
            conn.execute(
                text(
                    """
                    INSERT INTO materialize_plans (layout, tool_version, packs, files, blobs,
                        unique_bytes, linked_bytes, missing_blobs, free_bytes, totals)
                    VALUES (:layout, :ver, :packs, :files, :blobs, :ub, :lb, :mb, :fb, :totals)
                    RETURNING id
                    """
                ),
                {
                    "layout": opts.layout,
                    "ver": __version__,
                    "packs": totals["packs"],
                    "files": totals["files"],
                    "blobs": totals["blobs"],
                    "ub": totals["unique_bytes"],
                    "lb": totals["linked_bytes"],
                    "mb": totals["missing_blobs"],
                    "fb": opts.free_bytes,
                    "totals": json.dumps(totals, sort_keys=True),
                },
            ).scalar_one()
        )
        _write_units_and_blobs(conn, plan_id, need)
        _write_packs(conn, plan_id, planned)
        totals["plan_id"] = plan_id
        conn.execute(
            text("UPDATE materialize_plans SET totals = :t WHERE id = :id"),
            {"t": json.dumps(totals, sort_keys=True), "id": plan_id},
        )
    return PlanResult(plan_id=plan_id, totals=totals, packs=planned, blobs=need)


def _insert_unit(conn: Connection, plan_id: int, kind: str, root: int | None, blobs: list) -> int:
    return int(
        conn.execute(
            text(
                """
                INSERT INTO materialize_units (plan_id, kind, root_container_id, blobs, bytes,
                    source_bytes)
                VALUES (:p, :k, :r, :n, :b, :sb) RETURNING id
                """
            ),
            {
                "p": plan_id,
                "k": kind,
                "r": root,
                "n": len(blobs),
                "b": sum(b["size"] for b in blobs),
                "sb": (
                    blobs[0].get("root_source_bytes", 0)
                    if kind == "archive"
                    else sum(b["size"] for b in blobs)
                ),
            },
        ).scalar_one()
    )


def _write_units_and_blobs(conn: Connection, plan_id: int, need: dict[str, dict]) -> None:
    loose = sorted(
        (b for b in need.values() if b["source_kind"] == "loose"), key=lambda b: b["source_path"]
    )
    by_root: dict[int, list] = defaultdict(list)
    for b in need.values():
        if b["source_kind"] == "archive":
            by_root[b["root_container_id"]].append(b)
    for i in range(0, len(loose), LOOSE_UNIT_MAX_BLOBS):
        chunk = loose[i : i + LOOSE_UNIT_MAX_BLOBS]
        uid = _insert_unit(conn, plan_id, "loose", None, chunk)
        for b in chunk:
            b["unit_id"] = uid
    for root in sorted(by_root):
        blobs = by_root[root]
        uid = _insert_unit(conn, plan_id, "archive", root, blobs)
        for b in blobs:
            b["unit_id"] = uid
    rows = [
        {
            "p": plan_id,
            "sha": b["sha256"],
            "size": b["size"],
            "kind": b["kind"],
            "sk": b["source_kind"],
            "sp": b.get("source_path"),
            "ss": b.get("source_size"),
            "sm": b.get("source_mtime"),
            "root": b.get("root_container_id"),
            "chain": b.get("member_chain"),
            "uid": b.get("unit_id"),
            "state": "missing" if b["source_kind"] == "missing" else "pending",
            "err": "no_readable_source" if b["source_kind"] == "missing" else None,
        }
        for b in need.values()
    ]
    if rows:
        conn.execute(
            text(
                """
                INSERT INTO materialize_blobs (plan_id, sha256, size, kind, source_kind,
                    source_path, source_size, source_mtime, root_container_id, member_chain,
                    unit_id, state, error)
                VALUES (:p, :sha, :size, :kind, :sk, :sp, :ss, :sm, :root,
                    CAST(:chain AS text[]), :uid, :state, :err)
                """
            ),
            rows,
        )


def _write_packs(conn: Connection, plan_id: int, planned: list[PlannedPack]) -> None:
    if not planned:
        return
    conn.execute(
        text(
            """
            INSERT INTO materialize_packs (plan_id, pack_id, category, name, dir, files, bytes,
                meta)
            VALUES (:p, :pid, :cat, :name, :dir, :files, :bytes, :meta)
            """
        ),
        [
            {
                "p": plan_id,
                "pid": pk.pack_id,
                "cat": pk.category,
                "name": pk.name,
                "dir": pk.dir,
                "files": len(pk.files),
                "bytes": sum(f.size for f in pk.files),
                "meta": json.dumps(pk.meta, sort_keys=True, default=str),
            }
            for pk in planned
        ],
    )
    conn.execute(
        text(
            """
            INSERT INTO materialize_files (plan_id, pack_id, rel_path, sha256, size, kind,
                container_id, anchor_path, member_chain)
            VALUES (:p, :pid, :rel, :sha, :size, :kind, :cid, :anchor, CAST(:chain AS text[]))
            """
        ),
        [
            {
                "p": plan_id,
                "pid": pk.pack_id,
                "rel": f.rel_path,
                "sha": f.sha,
                "size": f.size,
                "kind": f.kind,
                "cid": f.container_id,
                "anchor": f.anchor_path,
                "chain": f.member_chain,
            }
            for pk in planned
            for f in pk.files
        ],
    )


def jsonl_lines(result: PlanResult):
    """Plan export: one totals line, then one line per pack with its files and blob sources."""
    yield json.dumps({"type": "totals", **result.totals}, sort_keys=True, default=str)
    for pk in result.packs:
        files = []
        for f in pk.files:
            b = result.blobs[f.sha]
            src = {"kind": b["source_kind"]}
            if b["source_kind"] == "loose":
                src["path"] = b["source_path"]
            elif b["source_kind"] == "archive":
                src["container_id"] = b["root_container_id"]
                src["member_chain"] = b["member_chain"]
            files.append(
                {"path": f.rel_path, "sha256": f.sha, "size": f.size, "kind": f.kind, "source": src}
            )
        yield json.dumps(
            {"type": "pack", "pack_id": pk.pack_id, "dir": pk.dir, "files": files, **pk.meta},
            sort_keys=True,
            default=str,
        )


def free_bytes_of(path: str | None) -> int | None:
    if not path or not os.path.isdir(path):
        return None
    st = os.statvfs(path)
    return int(st.f_bavail * st.f_frsize)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
