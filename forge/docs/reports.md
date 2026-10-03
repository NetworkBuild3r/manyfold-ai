# Forge reports — JSON schema (SPEC-014 input)

`forge report` writes catalog answers for “what do I actually have” and “which
STLs match across packs”. SPEC-014 renders a static site from the **JSON**
files. This document is the contract: keep `schema_version` stable; any
breaking field change bumps the version.

Provenance: `INIT-032/SPEC-009`.

## CLI

```text
forge report inventory  [--format json|csv|md] [--out DIR]
forge report duplicates [--format json|csv|md] [--out DIR]
                        [--min-copies N] [--limit N]
```

| Flag | Default | Meaning |
|---|---|---|
| `--format` | `json` | `json` (SPEC-014), `csv` (one file per table), `md` |
| `--out DIR` | stdout | write files into `DIR` (`inventory.json`, `duplicates.json`, …) |
| `--min-copies` | `2` | mesh blobs that occur in ≥ N distinct provisional packs |
| `--limit` | `500` | max rows in the blob list and the pair table (`0` = no cap) |

`--min-copies` applies to the **blob** list. The pair table includes every
provisional-pack pair that shares ≥ 1 mesh (SPEC-009), ranked by shared bytes,
then truncated by `--limit`.

Environment: `FORGE_DB_URL` (required; no localhost default). The command is
read-only (`SELECT` only) and sets `statement_timeout = 15min`.

### Provisional pack

SPEC-010 has not resolved packs yet. A **pack** here is:

- **archive** — the outer source archive (`source_files.path` of the root
  container; nested zips inherit that root);
- **loose_folder** — the parent directory of a loose file
  (`Games/Hero/model.stl` → `Games/Hero`).

### Public usage

```bash
# JSON for the report site (SPEC-014)
forge report inventory  --format json --out /reports
forge report duplicates --format json --out /reports --min-copies 2 --limit 500

# Human-readable
forge report inventory  --format md
forge report duplicates --format csv --out /tmp/dups --limit 0
```

## Common envelope

Every JSON document has:

| Field | Type | Notes |
|---|---|---|
| `schema_version` | int | **`1`** — bump only with a documented, additive-incompatible change |
| `report` | string | `"inventory"` or `"duplicates"` |
| `generated_at` | string | UTC `YYYY-MM-DDTHH:MM:SSZ` |
| `have` | object | “what do I actually have” (see below) |

### `have` (both reports)

| Field | Type | Meaning |
|---|---|---|
| `unique_meshes` | int | distinct `blobs` with `kind = mesh` |
| `unique_mesh_bytes` | int | sum of those blob sizes |
| `mesh_occurrences` | int | mesh rows in `occurrences` |
| `duplicate_ratio` | number | `(mesh_occurrences - unique_meshes) / mesh_occurrences` (0 if none) |
| `unique_bytes` | int | inventory only: sum of all blob sizes |
| `occurrence_bytes` | int | inventory only: Σ size over every occurrence |
| `mesh_occurrence_bytes` | int | inventory only |
| `cross_pack_blobs` | int | duplicates only |
| `reclaimable_bytes` | int | duplicates only: Σ `size × (copies − 1)` over cross-pack mesh blobs |

Ordering is deterministic: SQL `ORDER BY` on every table (name/kind ASC, or
count/bytes DESC then a unique key).

## `inventory.json`

```json
{
  "schema_version": 1,
  "report": "inventory",
  "generated_at": "2026-10-03T12:00:00Z",
  "summary": { "...catalog counts..." },
  "have": { "unique_meshes": 0, "unique_mesh_bytes": 0, "mesh_occurrences": 0, "duplicate_ratio": 0.0 },
  "asmt018": {
    "archived_mesh_members_hashed_before": 0,
    "archived_mesh_members_hashed_now": 0,
    "archived_unique_meshes_now": 0,
    "note": "ASMT-018: 0 of 718,974 archived mesh members had a digest"
  },
  "by_kind": [{ "kind": "mesh", "blobs": 0, "unique_bytes": 0, "occurrences": 0, "occurrence_bytes": 0 }],
  "by_format": [{ "kind": "archive", "format": "zip", "status": "done", "containers": 0, "members": 0, "bytes_read": 0, "source_bytes": 0 }],
  "by_top_level_folder": [{ "folder": "Games", "files": 0, "bytes": 0, "archives": 0, "loose": 0 }],
  "by_source_tag": [{ "tag": "AnySTL", "files": 0, "bytes": 0 }],
  "archives_vs_loose": [{ "kind": "archive", "files": 0, "bytes": 0 }],
  "depth_distribution": [{ "depth": 1, "containers": 0, "occurrences": 0 }],
  "failures": [{ "kind": "archive", "reason": "reader_error", "count": 0 }],
  "failed_containers": [{ "id": 1, "kind": "archive", "reason": "reader_error", "depth": 1, "path": "Games/x.rar" }],
  "meshes_by_ext": [{ "ext": "stl", "blobs": 0, "unique_bytes": 0, "occurrences": 0, "occurrence_bytes": 0 }],
  "stl_triangles": {
    "stl_blobs": 0,
    "with_triangles": 0,
    "missing_triangles": 0,
    "min_triangles": null,
    "max_triangles": null,
    "avg_triangles": null,
    "sum_triangles": 0,
    "unique_bytes": 0
  }
}
```

`failures[].count` summed equals `summary.failed_containers` and the
`forge status` failed-container total (same `status = 'failed'` predicate).

`by_source_tag.tag` is the first path component when it is one of
AnySTL, Cults3D, Gumroad, B3dserk, MyMiniFactory, Printables, Thingiverse
(case-insensitive match); otherwise `""`.

`asmt018.archived_mesh_members_hashed_now` is mesh occurrences whose container
`kind` is `archive` or `nested` — the number that was **0** in ASMT-018.

## `duplicates.json`

```json
{
  "schema_version": 1,
  "report": "duplicates",
  "generated_at": "2026-10-03T12:00:00Z",
  "min_copies": 2,
  "min_shared": 1,
  "limit": 500,
  "summary": { "unique_meshes": 0, "reclaimable_bytes": 0, "duplicate_ratio": 0.0 },
  "have": { "unique_meshes": 0, "unique_mesh_bytes": 0, "duplicate_ratio": 0.0, "reclaimable_bytes": 0 },
  "blobs": [
    {
      "sha256": "64 lowercase hex",
      "size": 0,
      "triangles": 0,
      "ext": "stl",
      "copies": 2,
      "reclaimable_bytes": 0,
      "sources": ["Pack.rar > inner.zip > model.stl"]
    }
  ],
  "pairs": [
    {
      "pack_a": "Games/alpha.zip",
      "pack_b": "Games/beta.zip",
      "kind_a": "archive",
      "kind_b": "archive",
      "meshes_a": 4,
      "meshes_b": 4,
      "bytes_a": 0,
      "bytes_b": 0,
      "shared_meshes": 3,
      "shared_bytes": 0,
      "containment_count": 0.75,
      "containment_bytes": 0.75,
      "overlap_a": 0.75,
      "overlap_b": 0.75,
      "overlap_a_bytes": 0.75,
      "overlap_b_bytes": 0.75,
      "archives_differ": true,
      "archive_sha_a": "64 hex or null",
      "archive_sha_b": "64 hex or null",
      "shared": [{ "sha256": "…", "size": 0, "name": "a.stl" }]
    }
  ]
}
```

| Pair field | Meaning |
|---|---|
| `containment_count` | `shared_meshes / min(meshes_a, meshes_b)` |
| `containment_bytes` | `shared_bytes / min(bytes_a, bytes_b)` |
| `overlap_a` / `overlap_b` | shared ÷ that pack’s mesh count (both ways) |
| `archives_differ` | `true` when both root-container `blob_sha` values are present and differ, **or** either hash is missing (different source files). `false` only when both hashes are present and equal |
| `shared` | one object per shared mesh blob, ordered by `sha256` |

`blobs[].sources` is the distinct chain-rendered paths
(`Pack.rar > inner.zip > model.stl`), sorted.

`reclaimable_bytes` on a blob is `size × (copies − 1)` — bytes you keep if one
copy of that mesh is retained. The summary sums that over every blob with
`copies >= min_copies` (not only the `--limit` page).

## Indexes / plans

No extra Alembic revision (`0003_reports`) shipped. Hot joins use
`ix_occurrences_blob_sha` and `ix_occurrences_container_id` from `0001`.
The pack-root walk is a recursive CTE on `containers` only. Tests
`EXPLAIN`-check the mesh→occurrence join (index, `enable_seqscan=off`)
and that the distinct-pack `GROUP BY` joins occurrences on `blob_sha`.
A tiny fixture seq-scans `occurrences`; production scale picks the index.

If a later sweep scale-out needs a covering index on
`(occurrences.blob_sha)` including `container_id`, add it as `0003_reports`
(`CREATE INDEX CONCURRENTLY`) — packs owns `0004`, materialize `0005`.

## Versioning

- **1** — first ship (SPEC-009).
- Add optional keys freely. Rename/remove/repurpose a key → new
  `schema_version` and a row in this file.
