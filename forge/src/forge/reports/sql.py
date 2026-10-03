"""Pure-SQL aggregations for inventory and cross-pack duplicates.

Occurrence scale is tens of millions: every number is a set-based query.
The recursive pack-root CTE walks ``containers`` only (tens of thousands).
Mesh facts start from ``blobs WHERE kind = 'mesh'`` and look up occurrences
via ``ix_occurrences_blob_sha``.

INIT-032/SPEC-009
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from forge.reports import SCHEMA_VERSION, SOURCE_TAGS

# Root of each container (parent_container_id walk). Nested rows inherit the
# outer archive's source_file_id and blob_sha so pack identity is the source
# archive, not the inner zip.
CONTAINER_ROOTS_SQL = """
container_roots AS (
  SELECT c.id, c.id AS root_id, c.kind AS root_kind,
         c.source_file_id AS root_source_file_id, c.blob_sha AS root_archive_sha
  FROM containers c
  WHERE c.parent_container_id IS NULL
  UNION ALL
  SELECT c.id, r.root_id, r.root_kind, r.root_source_file_id, r.root_archive_sha
  FROM containers c
  JOIN container_roots r ON c.parent_container_id = r.id
)
"""

# Provisional pack (ADR / SPEC-009): outer archive source path, or the leaf
# folder of a loose file.
_PACK_KEY = """
CASE
  WHEN c.kind = 'loose_batch' THEN
    CASE
      WHEN o.member_chain[1] LIKE '%/%'
        THEN regexp_replace(o.member_chain[1], '/[^/]+$', '')
      ELSE '.'
    END
  ELSE COALESCE(sf.path, 'container:' || r.root_id::text)
END
"""

_CHAIN = """
CASE
  WHEN c.kind = 'loose_batch' THEN array_to_string(o.member_chain, ' > ')
  ELSE concat_ws(
    ' > ',
    NULLIF(regexp_replace(COALESCE(sf.path, ''), '^.*/', ''), ''),
    NULLIF(array_to_string(o.member_chain, ' > '), '')
  )
END
"""

_SOURCE_TAG_SQL = (
    "CASE lower(split_part(sf.path, '/', 1)) "
    + " ".join(f"WHEN {tag!r} THEN split_part(sf.path, '/', 1)" for tag in SOURCE_TAGS)
    + " ELSE NULL END"
)

MESH_PACK_SQL = f"""
WITH RECURSIVE {CONTAINER_ROOTS_SQL}
SELECT
  b.sha256,
  b.size,
  b.stl_triangles,
  b.ext,
  {_PACK_KEY} AS pack_key,
  CASE WHEN c.kind = 'loose_batch' THEN 'loose_folder' ELSE 'archive' END AS pack_kind,
  r.root_archive_sha AS archive_sha,
  {_CHAIN} AS chain
FROM blobs b
JOIN occurrences o ON o.blob_sha = b.sha256
JOIN containers c ON c.id = o.container_id
JOIN container_roots r ON r.id = c.id
LEFT JOIN source_files sf ON sf.id = r.root_source_file_id
WHERE b.kind = 'mesh'
"""

INVENTORY_SUMMARY_SQL = """
SELECT
  (SELECT count(*) FROM source_files) AS source_files,
  (SELECT coalesce(sum(size), 0) FROM source_files) AS source_bytes,
  (SELECT count(*) FROM source_files WHERE kind = 'archive') AS archive_files,
  (SELECT coalesce(sum(size), 0) FROM source_files WHERE kind = 'archive') AS archive_bytes,
  (SELECT count(*) FROM source_files WHERE kind = 'loose') AS loose_files,
  (SELECT coalesce(sum(size), 0) FROM source_files WHERE kind = 'loose') AS loose_bytes,
  (SELECT count(*) FROM containers) AS containers,
  (SELECT count(*) FROM containers WHERE status = 'failed') AS failed_containers,
  (SELECT count(*) FROM blobs) AS blobs,
  (SELECT coalesce(sum(size), 0) FROM blobs) AS unique_bytes,
  (SELECT count(*) FROM occurrences) AS occurrences,
  (SELECT count(*) FROM blobs WHERE kind = 'mesh') AS unique_meshes,
  (SELECT coalesce(sum(size), 0) FROM blobs WHERE kind = 'mesh') AS unique_mesh_bytes
"""

OCCURRENCE_BYTES_SQL = """
SELECT coalesce(sum(b.size), 0) AS occurrence_bytes,
       count(*) FILTER (WHERE b.kind = 'mesh') AS mesh_occurrences,
       coalesce(sum(b.size) FILTER (WHERE b.kind = 'mesh'), 0) AS mesh_occurrence_bytes
FROM blobs b
JOIN occurrences o ON o.blob_sha = b.sha256
"""

BY_KIND_SQL = """
WITH occ AS (
  SELECT b.kind::text AS kind,
         count(*) AS occurrences,
         coalesce(sum(b.size), 0) AS occurrence_bytes
  FROM blobs b
  JOIN occurrences o ON o.blob_sha = b.sha256
  GROUP BY b.kind
)
SELECT
  b.kind::text AS kind,
  count(*) AS blobs,
  coalesce(sum(b.size), 0) AS unique_bytes,
  coalesce(occ.occurrences, 0) AS occurrences,
  coalesce(occ.occurrence_bytes, 0) AS occurrence_bytes
FROM blobs b
LEFT JOIN occ ON occ.kind = b.kind::text
GROUP BY b.kind, occ.occurrences, occ.occurrence_bytes
ORDER BY b.kind
"""

BY_FORMAT_SQL = """
SELECT
  c.kind::text AS kind,
  coalesce(c.format, '') AS format,
  c.status::text AS status,
  count(*) AS containers,
  coalesce(sum(c.members), 0) AS members,
  coalesce(sum(c.bytes_read), 0) AS bytes_read,
  coalesce(sum(c.source_bytes), 0) AS source_bytes
FROM containers c
GROUP BY c.kind, c.format, c.status
ORDER BY c.kind, c.format, c.status
"""

BY_FOLDER_SQL = """
SELECT
  COALESCE(NULLIF(split_part(sf.path, '/', 1), ''), '.') AS folder,
  count(*) AS files,
  coalesce(sum(sf.size), 0) AS bytes,
  count(*) FILTER (WHERE sf.kind = 'archive') AS archives,
  count(*) FILTER (WHERE sf.kind = 'loose') AS loose
FROM source_files sf
GROUP BY 1
ORDER BY 1
"""

BY_SOURCE_TAG_SQL = f"""
SELECT
  COALESCE({_SOURCE_TAG_SQL}, '') AS tag,
  count(*) AS files,
  coalesce(sum(sf.size), 0) AS bytes
FROM source_files sf
GROUP BY 1
ORDER BY 1
"""

DEPTH_SQL = """
SELECT
  d.depth,
  coalesce(c.containers, 0) AS containers,
  coalesce(o.occurrences, 0) AS occurrences
FROM (
  SELECT depth FROM containers
  UNION
  SELECT depth FROM occurrences
) d
LEFT JOIN (
  SELECT depth, count(*) AS containers FROM containers GROUP BY depth
) c ON c.depth = d.depth
LEFT JOIN (
  SELECT depth, count(*) AS occurrences FROM occurrences GROUP BY depth
) o ON o.depth = d.depth
ORDER BY d.depth
"""

FAILURES_SQL = """
SELECT
  c.kind::text AS kind,
  coalesce(c.failure_reason::text, 'unknown') AS reason,
  count(*) AS count
FROM containers c
WHERE c.status = 'failed'
GROUP BY 1, 2
ORDER BY count DESC, kind, reason
"""

FAILED_CONTAINERS_SQL = """
SELECT
  c.id,
  c.kind::text AS kind,
  coalesce(c.failure_reason::text, 'unknown') AS reason,
  c.depth,
  sf.path
FROM containers c
LEFT JOIN source_files sf ON sf.id = c.source_file_id
WHERE c.status = 'failed'
ORDER BY reason, sf.path NULLS LAST, c.id
"""

MESHES_BY_EXT_SQL = """
WITH occ AS (
  SELECT coalesce(b.ext, '') AS ext,
         count(*) AS occurrences,
         coalesce(sum(b.size), 0) AS occurrence_bytes
  FROM blobs b
  JOIN occurrences o ON o.blob_sha = b.sha256
  WHERE b.kind = 'mesh'
  GROUP BY 1
)
SELECT
  coalesce(b.ext, '') AS ext,
  count(*) AS blobs,
  coalesce(sum(b.size), 0) AS unique_bytes,
  coalesce(occ.occurrences, 0) AS occurrences,
  coalesce(occ.occurrence_bytes, 0) AS occurrence_bytes
FROM blobs b
LEFT JOIN occ ON occ.ext = coalesce(b.ext, '')
WHERE b.kind = 'mesh'
GROUP BY coalesce(b.ext, ''), occ.occurrences, occ.occurrence_bytes
ORDER BY 1
"""

STL_STATS_SQL = """
SELECT
  count(*) AS stl_blobs,
  count(stl_triangles) AS with_triangles,
  count(*) FILTER (WHERE stl_triangles IS NULL) AS missing_triangles,
  min(stl_triangles) AS min_triangles,
  max(stl_triangles) AS max_triangles,
  avg(stl_triangles)::double precision AS avg_triangles,
  coalesce(sum(stl_triangles), 0) AS sum_triangles,
  coalesce(sum(size), 0) AS unique_bytes
FROM blobs
WHERE kind = 'mesh' AND ext = 'stl'
"""

ASMT018_SQL = """
SELECT
  count(*) AS archived_mesh_members_hashed_now,
  count(DISTINCT o.blob_sha) AS archived_unique_meshes_now
FROM blobs b
JOIN occurrences o ON o.blob_sha = b.sha256
JOIN containers c ON c.id = o.container_id
WHERE b.kind = 'mesh' AND c.kind IN ('archive', 'nested')
"""

DUP_BLOBS_SQL = f"""
WITH mesh AS (
  {MESH_PACK_SQL}
),
per_pack AS (
  SELECT sha256, size, stl_triangles, ext, pack_key
  FROM mesh
  GROUP BY sha256, size, stl_triangles, ext, pack_key
),
agg AS (
  SELECT
    sha256,
    min(size) AS size,
    min(stl_triangles) AS triangles,
    min(ext) AS ext,
    count(*) AS copies
  FROM per_pack
  GROUP BY sha256
  HAVING count(*) >= :min_copies
)
SELECT
  a.sha256,
  a.size,
  a.triangles,
  a.ext,
  a.copies,
  a.size * (a.copies - 1) AS reclaimable_bytes,
  (
    SELECT coalesce(array_agg(x.chain ORDER BY x.chain), ARRAY[]::text[])
    FROM (SELECT DISTINCT m.chain FROM mesh m WHERE m.sha256 = a.sha256) x
  ) AS sources
FROM agg a
ORDER BY a.copies DESC, a.size DESC, a.sha256
LIMIT :lim
"""

DUP_SUMMARY_SQL = f"""
WITH mesh AS (
  {MESH_PACK_SQL}
),
per_pack AS (
  SELECT sha256, size, pack_key
  FROM mesh
  GROUP BY sha256, size, pack_key
),
dup AS (
  SELECT sha256, min(size) AS size, count(*) AS copies
  FROM per_pack
  GROUP BY sha256
  HAVING count(*) >= :min_copies
)
SELECT
  (SELECT count(*) FROM blobs WHERE kind = 'mesh') AS unique_meshes,
  (SELECT coalesce(sum(size), 0) FROM blobs WHERE kind = 'mesh') AS unique_mesh_bytes,
  (SELECT count(*) FROM mesh) AS mesh_occurrences,
  (SELECT count(*) FROM dup) AS cross_pack_blobs,
  (SELECT coalesce(sum(size * (copies - 1)), 0) FROM dup) AS reclaimable_bytes
"""

# Pairs of provisional packs sharing >= :min_shared mesh blobs.
# containment_* = shared ÷ the smaller pack (SPEC-009 AC1: 3/4 = 0.75).
# overlap_* = shared ÷ that pack (both directions).
DUP_PAIRS_SQL = f"""
WITH mesh AS (
  {MESH_PACK_SQL}
),
pack_blob AS (
  SELECT pack_key, pack_kind, sha256, min(size) AS size,
         min(archive_sha) AS archive_sha,
         min(split_part(chain, ' > ', greatest(1, array_length(string_to_array(chain, ' > '), 1))))
           AS member_name
  FROM mesh
  GROUP BY pack_key, pack_kind, sha256
),
pack_tot AS (
  SELECT pack_key, pack_kind, min(archive_sha) AS archive_sha,
         count(*) AS meshes, coalesce(sum(size), 0) AS mesh_bytes
  FROM pack_blob
  GROUP BY pack_key, pack_kind
),
shared AS (
  SELECT
    a.pack_key AS pack_a,
    b.pack_key AS pack_b,
    a.pack_kind AS kind_a,
    b.pack_kind AS kind_b,
    count(*) AS shared_meshes,
    coalesce(sum(a.size), 0) AS shared_bytes,
    json_agg(
      json_build_object(
        'sha256', a.sha256,
        'size', a.size,
        'name', a.member_name
      )
      ORDER BY a.sha256
    ) AS shared
  FROM pack_blob a
  JOIN pack_blob b
    ON a.sha256 = b.sha256
   AND a.pack_key < b.pack_key
  GROUP BY a.pack_key, b.pack_key, a.pack_kind, b.pack_kind
  HAVING count(*) >= :min_shared
)
SELECT
  s.pack_a,
  s.pack_b,
  s.kind_a,
  s.kind_b,
  ta.meshes AS meshes_a,
  tb.meshes AS meshes_b,
  ta.mesh_bytes AS bytes_a,
  tb.mesh_bytes AS bytes_b,
  s.shared_meshes,
  s.shared_bytes,
  CASE WHEN least(ta.meshes, tb.meshes) = 0 THEN 0
       ELSE s.shared_meshes::double precision / least(ta.meshes, tb.meshes)
  END AS containment_count,
  CASE WHEN least(ta.mesh_bytes, tb.mesh_bytes) = 0 THEN 0
       ELSE s.shared_bytes::double precision / least(ta.mesh_bytes, tb.mesh_bytes)
  END AS containment_bytes,
  CASE WHEN ta.meshes = 0 THEN 0
       ELSE s.shared_meshes::double precision / ta.meshes END AS overlap_a,
  CASE WHEN tb.meshes = 0 THEN 0
       ELSE s.shared_meshes::double precision / tb.meshes END AS overlap_b,
  CASE WHEN ta.mesh_bytes = 0 THEN 0
       ELSE s.shared_bytes::double precision / ta.mesh_bytes END AS overlap_a_bytes,
  CASE WHEN tb.mesh_bytes = 0 THEN 0
       ELSE s.shared_bytes::double precision / tb.mesh_bytes END AS overlap_b_bytes,
  CASE
    WHEN ta.archive_sha IS NOT NULL AND tb.archive_sha IS NOT NULL
      THEN ta.archive_sha IS DISTINCT FROM tb.archive_sha
    ELSE TRUE
  END AS archives_differ,
  ta.archive_sha AS archive_sha_a,
  tb.archive_sha AS archive_sha_b,
  s.shared
FROM shared s
JOIN pack_tot ta ON ta.pack_key = s.pack_a
JOIN pack_tot tb ON tb.pack_key = s.pack_b
ORDER BY s.shared_bytes DESC, s.pack_a, s.pack_b
LIMIT :lim
"""

# EXPLAIN targets — same join order as the live report.
EXPLAIN_MESH_OCC_SQL = """
SELECT b.sha256, o.container_id, o.depth
FROM blobs b
JOIN occurrences o ON o.blob_sha = b.sha256
WHERE b.kind = 'mesh'
"""

EXPLAIN_DUP_GROUP_SQL = f"""
WITH RECURSIVE {CONTAINER_ROOTS_SQL}
SELECT b.sha256, count(DISTINCT {_PACK_KEY}) AS copies
FROM blobs b
JOIN occurrences o ON o.blob_sha = b.sha256
JOIN containers c ON c.id = o.container_id
JOIN container_roots r ON r.id = c.id
LEFT JOIN source_files sf ON sf.id = r.root_source_file_id
WHERE b.kind = 'mesh'
GROUP BY b.sha256
HAVING count(DISTINCT {_PACK_KEY}) >= 2
"""


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "as_tuple"):
        as_int = int(value)
        return as_int if as_int == value else float(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def _row(mapping: Any) -> dict[str, Any]:
    return {k: _jsonable(v) for k, v in dict(mapping).items()}


def _ratio(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return round(num / den, 6)


def fetch_all(conn: Connection, sql: str, **params: Any) -> list[dict[str, Any]]:
    return [_row(r) for r in conn.execute(text(sql), params).mappings()]


def fetch_one(conn: Connection, sql: str, **params: Any) -> dict[str, Any]:
    row = conn.execute(text(sql), params).mappings().first()
    return _row(row) if row is not None else {}


def collect_inventory(conn: Connection) -> dict[str, Any]:
    """Build the versioned inventory document."""
    summary = fetch_one(conn, INVENTORY_SUMMARY_SQL)
    occ = fetch_one(conn, OCCURRENCE_BYTES_SQL)
    asmt = fetch_one(conn, ASMT018_SQL)
    stl = fetch_one(conn, STL_STATS_SQL)
    unique_meshes = int(summary.get("unique_meshes") or 0)
    unique_mesh_bytes = int(summary.get("unique_mesh_bytes") or 0)
    mesh_occ = int(occ.get("mesh_occurrences") or 0)
    mesh_occ_bytes = int(occ.get("mesh_occurrence_bytes") or 0)
    have = {
        "unique_meshes": unique_meshes,
        "unique_mesh_bytes": unique_mesh_bytes,
        "mesh_occurrences": mesh_occ,
        "mesh_occurrence_bytes": mesh_occ_bytes,
        "duplicate_ratio": _ratio(mesh_occ - unique_meshes, mesh_occ),
        "unique_bytes": int(summary.get("unique_bytes") or 0),
        "occurrence_bytes": int(occ.get("occurrence_bytes") or 0),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "report": "inventory",
        "summary": {
            **summary,
            **occ,
            "failed_containers": int(summary.get("failed_containers") or 0),
        },
        "have": have,
        "asmt018": {
            "archived_mesh_members_hashed_before": 0,
            "archived_mesh_members_hashed_now": int(
                asmt.get("archived_mesh_members_hashed_now") or 0
            ),
            "archived_unique_meshes_now": int(asmt.get("archived_unique_meshes_now") or 0),
            "note": "ASMT-018: 0 of 718,974 archived mesh members had a digest",
        },
        "by_kind": fetch_all(conn, BY_KIND_SQL),
        "by_format": fetch_all(conn, BY_FORMAT_SQL),
        "by_top_level_folder": fetch_all(conn, BY_FOLDER_SQL),
        "by_source_tag": fetch_all(conn, BY_SOURCE_TAG_SQL),
        "archives_vs_loose": [
            {
                "kind": "archive",
                "files": int(summary.get("archive_files") or 0),
                "bytes": int(summary.get("archive_bytes") or 0),
            },
            {
                "kind": "loose",
                "files": int(summary.get("loose_files") or 0),
                "bytes": int(summary.get("loose_bytes") or 0),
            },
        ],
        "depth_distribution": fetch_all(conn, DEPTH_SQL),
        "failures": fetch_all(conn, FAILURES_SQL),
        "failed_containers": fetch_all(conn, FAILED_CONTAINERS_SQL),
        "meshes_by_ext": fetch_all(conn, MESHES_BY_EXT_SQL),
        "stl_triangles": stl,
    }


def collect_duplicates(
    conn: Connection,
    *,
    min_copies: int = 2,
    min_shared: int = 1,
    limit: int | None = None,
) -> dict[str, Any]:
    """Build the versioned cross-pack duplicates document."""
    lim = 2_147_483_647 if limit is None or limit <= 0 else int(limit)
    min_copies = max(1, int(min_copies))
    min_shared = max(1, int(min_shared))
    summary = fetch_one(conn, DUP_SUMMARY_SQL, min_copies=min_copies)
    blobs = fetch_all(conn, DUP_BLOBS_SQL, min_copies=min_copies, lim=lim)
    pairs = fetch_all(conn, DUP_PAIRS_SQL, min_shared=min_shared, lim=lim)
    for pair in pairs:
        shared = pair.get("shared")
        if isinstance(shared, str):
            pair["shared"] = json.loads(shared)
        elif shared is None:
            pair["shared"] = []
        pair["archives_differ"] = bool(pair.get("archives_differ"))
    unique_meshes = int(summary.get("unique_meshes") or 0)
    unique_mesh_bytes = int(summary.get("unique_mesh_bytes") or 0)
    mesh_occ = int(summary.get("mesh_occurrences") or 0)
    reclaimable = int(summary.get("reclaimable_bytes") or 0)
    return {
        "schema_version": SCHEMA_VERSION,
        "report": "duplicates",
        "min_copies": min_copies,
        "min_shared": min_shared,
        "limit": None if limit is None or limit <= 0 else lim,
        "summary": {
            **summary,
            "duplicate_ratio": _ratio(mesh_occ - unique_meshes, mesh_occ),
            "reclaimable_bytes": reclaimable,
        },
        "have": {
            "unique_meshes": unique_meshes,
            "unique_mesh_bytes": unique_mesh_bytes,
            "mesh_occurrences": mesh_occ,
            "duplicate_ratio": _ratio(mesh_occ - unique_meshes, mesh_occ),
            "cross_pack_blobs": int(summary.get("cross_pack_blobs") or 0),
            "reclaimable_bytes": reclaimable,
        },
        "blobs": blobs,
        "pairs": pairs,
    }
