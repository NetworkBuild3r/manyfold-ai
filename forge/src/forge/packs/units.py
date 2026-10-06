"""Resolution units: source containers and loose-folder groups.

- archive unit = one top-level archive container (a volume set is one container) plus every nested
  container under it. Key ``archive:<first volume path>``.
- loose unit = the loose files of one *model root* — the deepest folder holding a
  ``datapackage.json`` (Manyfold / spark-curate model folder) — or, when there is no model root or
  the root is a bundle, of one leaf folder. Key ``loose:<folder>``.
- co-location: every unit under the same non-bundle model root shares a ``coloc`` key, which
  resolution uses to attach mesh-less units (previews, img.zip) to the root's pack (or, with
  ``colocate=all``, to join every unit of the root). A root with more than ``bundle_items`` direct
  items (archives + loose leaf folders) is a bundle and is not co-located (e.g. a dump folder
  holding thousands of products).

Pure planning lives here (no DB); ``refresh_units`` persists the plan and the mesh sets.

INIT-032/SPEC-010
"""

from __future__ import annotations

import posixpath
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Connection

from forge.packs.sqlutil import copy_rows, temp_table

MODEL_ROOT_MARKER = "datapackage.json"
TERMINAL = frozenset({"done", "failed"})


@dataclass
class UnitSpec:
    key: str
    kind: str  # archive | loose
    path: str
    model_root: str | None
    root_container_id: int | None = None
    complete: bool = True
    coloc: str | None = None
    source_file_ids: list[int] = field(default_factory=list)
    loose_paths: list[str] = field(default_factory=list)
    container_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class SourceRow:
    id: int
    path: str
    kind: str


@dataclass(frozen=True)
class ContainerRow:
    id: int
    kind: str
    source_file_id: int | None
    parent_id: int | None
    status: str
    requeued_from_id: int | None = None
    # A volume catalogued alone before its multi-volume set was resolved (0007): not a unit.
    superseded_by_id: int | None = None


class ModelRoots:
    def __init__(self, paths: Iterable[str]) -> None:
        self.dirs = {
            posixpath.dirname(p) for p in paths if posixpath.basename(p) == MODEL_ROOT_MARKER
        }
        self._memo: dict[str, str | None] = {}

    def root_of_dir(self, d: str) -> str | None:
        if d in self._memo:
            return self._memo[d]
        chain = []
        cur: str | None = d
        found: str | None = None
        while cur is not None:
            if cur in self._memo:
                found = self._memo[cur]
                break
            chain.append(cur)
            if cur in self.dirs:
                found = cur
                break
            cur = posixpath.dirname(cur) if cur else None
        for c in chain:
            self._memo[c] = found if (found is not None and _under(c, found)) else None
        return self._memo[d]


def _under(d: str, root: str) -> bool:
    return d == root or root == "" or d.startswith(root + "/")


def plan_units(
    sources: Iterable[SourceRow],
    containers: Iterable[ContainerRow],
    container_files: Iterable[tuple[int, int]],
    *,
    bundle_items: int = 24,
) -> list[UnitSpec]:
    src = {s.id: s for s in sources}
    roots = ModelRoots(s.path for s in src.values())
    cont = {c.id: c for c in containers}
    requeued = {c.requeued_from_id for c in cont.values() if c.requeued_from_id}

    files_of: dict[int, list[int]] = defaultdict(list)
    batches_of_file: dict[int, list[int]] = defaultdict(list)
    for cid, sid in container_files:
        files_of[cid].append(sid)
        c = cont.get(cid)
        if c is not None and c.kind == "loose_batch":
            batches_of_file[sid].append(cid)

    # nested containers -> top-level archive
    def top_of(cid: int) -> int:
        seen = 0
        while cont[cid].parent_id is not None and cont[cid].parent_id in cont and seen < 64:
            cid = cont[cid].parent_id
            seen += 1
        return cid

    subtree: dict[int, list[int]] = defaultdict(list)
    for c in cont.values():
        if c.kind == "nested":
            subtree[top_of(c.id)].append(c.id)

    archive_tops = [
        c
        for c in cont.values()
        if c.kind == "archive"
        and c.parent_id is None
        and c.id not in requeued
        and c.superseded_by_id is None
    ]
    archive_tops.sort(key=lambda c: c.id)

    # bundle detection: direct items per model root
    items: dict[str, set[str]] = defaultdict(set)
    arch_info: list[tuple[ContainerRow, str, str | None]] = []
    for c in archive_tops:
        first = src.get(c.source_file_id) if c.source_file_id else None
        if first is None:
            continue
        root = roots.root_of_dir(posixpath.dirname(first.path))
        arch_info.append((c, first.path, root))
        if root is not None:
            items[root].add("a:" + first.path)
    loose_info: list[tuple[SourceRow, str, str | None]] = []
    for sid, batches in batches_of_file.items():
        s = src.get(sid)
        if s is None:
            continue
        d = posixpath.dirname(s.path)
        root = roots.root_of_dir(d)
        loose_info.append((s, d, root))
        if root is not None:
            items[root].add("d:" + d)
    bundles = {r for r, its in items.items() if len(its) > bundle_items}

    units: list[UnitSpec] = []
    for c, path, root in arch_info:
        tree = [c.id, *subtree.get(c.id, [])]
        complete = all(cont[x].status in TERMINAL for x in tree)
        units.append(
            UnitSpec(
                key="archive:" + path,
                kind="archive",
                path=path,
                model_root=root,
                root_container_id=c.id,
                complete=complete,
                coloc=root if (root is not None and root not in bundles) else None,
                source_file_ids=sorted(files_of.get(c.id, [c.source_file_id])),
                container_ids=tree,
            )
        )

    loose_units: dict[str, UnitSpec] = {}
    for s, d, root in sorted(loose_info, key=lambda t: t[0].path):
        folder = root if (root is not None and root not in bundles) else d
        key = "loose:" + folder
        u = loose_units.get(key)
        if u is None:
            u = UnitSpec(
                key=key,
                kind="loose",
                path=folder,
                model_root=root,
                coloc=root if (root is not None and root not in bundles) else None,
            )
            loose_units[key] = u
        u.source_file_ids.append(s.id)
        u.loose_paths.append(s.path)
        for b in batches_of_file[s.id]:
            if b not in u.container_ids:
                u.container_ids.append(b)
            if cont[b].status not in TERMINAL:
                u.complete = False
    units.extend(loose_units[k] for k in sorted(loose_units))
    return units


# --------------------------------------------------------------------------------------- persist


def load_plan(conn: Connection, *, bundle_items: int) -> list[UnitSpec]:
    sources = [
        SourceRow(int(r[0]), r[1], r[2])
        for r in conn.execute(text("SELECT id, path, kind::text FROM source_files WHERE present"))
    ]
    containers = [
        ContainerRow(int(r[0]), r[1], r[2], r[3], r[4], r[5], r[6])
        for r in conn.execute(
            text(
                "SELECT id, kind::text, source_file_id, parent_container_id, status::text, "
                "requeued_from_id, superseded_by_id FROM containers"
            )
        )
    ]
    cfiles = [
        (int(r[0]), int(r[1]))
        for r in conn.execute(text("SELECT container_id, source_file_id FROM container_files"))
    ]
    return plan_units(sources, containers, cfiles, bundle_items=bundle_items)


def refresh_units(conn: Connection, plan: list[UnitSpec]) -> dict[str, int]:
    """Upsert pack_units from the plan; rebuild unit sources, mesh sets and stats (set-based)."""
    temp_table(
        conn,
        "tmp_units",
        "unit_key text PRIMARY KEY, kind text, path text, model_root text, coloc_root text, "
        "root_container_id bigint, complete boolean",
    )
    copy_rows(
        conn,
        "tmp_units",
        ("unit_key", "kind", "path", "model_root", "coloc_root", "root_container_id", "complete"),
        (
            (u.key, u.kind, u.path, u.model_root, u.coloc, u.root_container_id, u.complete)
            for u in plan
        ),
    )
    conn.execute(
        text(
            """
            INSERT INTO pack_units (unit_key, kind, path, model_root, coloc_root,
                                    root_container_id, complete, present, updated_at)
            SELECT unit_key, kind, path, model_root, coloc_root, root_container_id, complete,
                   true, now()
            FROM tmp_units
            ON CONFLICT (unit_key) DO UPDATE SET
                kind = EXCLUDED.kind, path = EXCLUDED.path, model_root = EXCLUDED.model_root,
                coloc_root = EXCLUDED.coloc_root, root_container_id = EXCLUDED.root_container_id,
                complete = EXCLUDED.complete, present = true, updated_at = now()
            """
        )
    )
    conn.execute(
        text(
            """
            UPDATE pack_units SET present = false, complete = false, pack_id = NULL, role = NULL,
                   updated_at = now()
            WHERE present AND unit_key NOT IN (SELECT unit_key FROM tmp_units)
            """
        )
    )
    ids = {
        r[1]: int(r[0])
        for r in conn.execute(text("SELECT id, unit_key FROM pack_units WHERE present"))
    }

    conn.execute(text("DELETE FROM pack_unit_sources"))
    copy_rows(
        conn,
        "pack_unit_sources",
        ("unit_id", "source_file_id"),
        ((ids[u.key], sid) for u in plan for sid in sorted(set(u.source_file_ids))),
    )

    temp_table(conn, "tmp_container_unit", "container_id bigint PRIMARY KEY, unit_id bigint")
    copy_rows(
        conn,
        "tmp_container_unit",
        ("container_id", "unit_id"),
        (
            (cid, ids[u.key])
            for u in plan
            if u.kind == "archive" and u.complete
            for cid in u.container_ids
        ),
    )
    temp_table(conn, "tmp_loose_path", "path text PRIMARY KEY, unit_id bigint")
    copy_rows(
        conn,
        "tmp_loose_path",
        ("path", "unit_id"),
        ((p, ids[u.key]) for u in plan if u.kind == "loose" and u.complete for p in u.loose_paths),
    )
    conn.execute(text("ANALYZE tmp_container_unit"))
    conn.execute(text("ANALYZE tmp_loose_path"))

    # Streaming aggregates over occurrences (no per-occurrence temp table at tens of millions).
    unit_occ = """
        SELECT cu.unit_id, o.blob_sha, b.kind
        FROM occurrences o
        JOIN tmp_container_unit cu ON cu.container_id = o.container_id
        JOIN blobs b ON b.sha256 = o.blob_sha
        WHERE b.kind <> 'archive'
        UNION ALL
        SELECT lp.unit_id, o.blob_sha, b.kind
        FROM occurrences o
        JOIN containers c ON c.id = o.container_id AND c.kind = 'loose_batch'
        JOIN tmp_loose_path lp ON lp.path = o.member_chain[1]
        JOIN blobs b ON b.sha256 = o.blob_sha
        WHERE b.kind <> 'archive'
    """
    conn.execute(text("TRUNCATE pack_unit_meshes"))
    conn.execute(
        text(
            f"""
            INSERT INTO pack_unit_meshes (unit_id, blob_sha)
            SELECT DISTINCT unit_id, blob_sha FROM ({unit_occ}) x WHERE kind = 'mesh'
            """
        )
    )
    conn.execute(
        text(
            """
            UPDATE pack_units SET file_count = 0, image_count = 0, mesh_count = 0, mesh_bytes = 0,
                   tri_sum = 0, set_hash = NULL
            WHERE present
            """
        )
    )
    conn.execute(
        text(
            f"""
            UPDATE pack_units u SET file_count = s.files, image_count = s.images
            FROM (SELECT unit_id, count(*) AS files,
                         count(*) FILTER (WHERE kind = 'image') AS images
                  FROM ({unit_occ}) x GROUP BY unit_id) s
            WHERE u.id = s.unit_id
            """
        )
    )
    conn.execute(
        text(
            """
            UPDATE pack_units u SET mesh_count = s.n, mesh_bytes = s.bytes, tri_sum = s.tri,
                   set_hash = s.h
            FROM (SELECT m.unit_id, count(*) AS n, sum(b.size) AS bytes,
                         sum(coalesce(b.stl_triangles, 0)) AS tri,
                         md5(string_agg(m.blob_sha, ',' ORDER BY m.blob_sha)) AS h
                  FROM pack_unit_meshes m JOIN blobs b ON b.sha256 = m.blob_sha
                  GROUP BY m.unit_id) s
            WHERE u.id = s.unit_id
            """
        )
    )
    return {
        "units": len(plan),
        "units_complete": sum(1 for u in plan if u.complete),
        "units_archive": sum(1 for u in plan if u.kind == "archive"),
        "units_loose": sum(1 for u in plan if u.kind == "loose"),
    }
