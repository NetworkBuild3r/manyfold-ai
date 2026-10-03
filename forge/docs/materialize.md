# forge materialize — the v2 tree (INIT-032/SPEC-012)

`v2 = materialize(catalog, decisions)` (ADR D-4). The v2 tree is derived: delete it and re-run.
This is the only forge component that writes files, and it writes **only under the v2 root**
(plus a local scratch dir).

```
<v2>/.forge-blobs/<aa>/<bb>/<sha256>      blob store: one inode per unique blob (ADR D-6/D-6a)
<v2>/<Category>/<Pack>/<relative path>     pack files: hardlinks of the store inode
<v2>/<Category>/<Pack>/datapackage.json    provenance
```

## Safety model (read this first)

The hard line: **nothing under the source root (`3D-Prints`) is ever deleted, modified, renamed
or opened for write.** Enforcement, in the order an auditor should read it:

1. **`src/forge/materialize/guard.py`** — the *only* module that calls filesystem write
   primitives. `WriteGuard.check(path, area)` resolves the parent with `realpath` (symlinks
   followed as the kernel would), rejects `.`/`..`/empty/NUL, rejects anything equal to or
   under the source root, and requires the result to be *strictly* under the v2 root (or the
   scratch root for spools). The primitive then acts on the *resolved* path. New files are only
   created with `O_CREAT|O_EXCL|O_NOFOLLOW` — an existing v2 name (which may be a hardlink of a
   source inode) is never opened for write, truncated, chmod'ed or utime'd. Replacing a wrong
   pack file means a new temp name + `rename()` over the old *name*; no existing inode's bytes
   change. A hardlink *source* must itself resolve under the source or v2 root
   (`check_link_source`), so a directory symlink planted in the source tree cannot pull an
   arbitrary file into v2.
2. **`tests/materialize/test_fence.py`** — AST fence: any write primitive (`os.link/rename/
   replace/unlink/mkdir/chmod/utime/...`, `Path.write_*`, write-mode `open`, `os.open`,
   `shutil`, `tempfile`) outside `guard.py` fails CI. It includes a planted-violation test.
3. **`tests/materialize/test_apply.py::test_every_write_lands_under_v2_or_scratch`** — a Python
   audit hook records every write-ish syscall during a full apply + verify + gc and asserts each
   target resolves under v2/scratch and none under the source; the source tree's
   `(sha256, size, mtime_ns, mode)` snapshot is identical afterwards.
4. **Startup checks (`open_guard`)** — roots absolute and pairwise disjoint; scratch local (not
   NFS); if source and v2 are on *different* filesystems the source mount must be read-only
   (AC4); if they share one filesystem (ADR D-6a, required for `link(source, v2)`) the operator
   must set `FORGE_SOURCE_SHARED_MOUNT=1`, and the guard is then the enforcement. A guard
   self-test refuses the source root at startup.
5. **Plan paths are untrusted too** — `join_v2()` refuses any plan row whose path is not a plain
   relative path (`tests: test_hostile_plan_path_is_refused_and_source_untouched`), and catalog
   source paths are checked the same way before a read (`test_hostile_catalog_source_path_...`).
   A refusal fails that unit/pack (`guard_refused`), other work continues, and the process exits
   **3**.

What hardlinking a source file *does* change: the source inode's link count and ctime (a new
name exists in v2). Bytes, size, mtime and permissions are unchanged; `audit-source` checks
size + mtime against the catalog.

Accepted residual risk: check-then-act is not atomic against a concurrent attacker replacing a
v2 directory with a symlink between the check and the syscall. Only forge writes v2.

## Commands

All read `FORGE_DB_URL`; filesystem commands need `FORGE_V2_ROOT`, `FORGE_SOURCE_ROOT`,
`FORGE_SCRATCH`, and (single NFS mount) `FORGE_SOURCE_SHARED_MOUNT=1`. No path defaults exist.

| Command | Effect |
| --- | --- |
| `forge materialize plan [--layout tree\|flat] [--pack ID]... [--include-provisional] [--out PATH\|-]` | DB only. Supersedes the active plan. Prints totals (packs, files, unique/linked bytes, loose/archive/missing blobs, archive bytes to read, write bytes, free space). `--out` JSONL goes under v2 or scratch only; `<v2>/.forge-plan/` is reserved for exports and is never a stray. Refuses while an apply holds claims (`--force`). |
| `forge materialize preflight [--sample N]` | Startup checks + free space + `link(source_file, v2/.forge-blobs/.preflight-*)` probes on N random loose source files (each probe name removed again), with an owner/mode histogram. Exit 1 if any link is refused. Run this before every real apply. |
| `forge materialize status [--plan ID]` | Units / blobs / packs by state, bytes done, first 50 errors. |
| `forge materialize apply [--pack ID... \| --limit N] [--resume] [--retry-failed] [--procs N] [--io-mbps M] [--no-copy-fallback] [--verify-loose]` | Executes the active plan. Exit 0 ok, 1 some unit/pack errored, 3 guard refusal. |
| `forge materialize verify [--sample N \| --all] [--tree-hash] [--no-strays]` | Store entries, pack files, link counts, sha256 (one hash per inode), strays. Exit 1 on any problem. |
| `forge materialize audit-source [--sample N]` | `stat()` every present catalog source file; reports missing / size / mtime drift. Never opens a file. |
| `forge materialize gc-plan [--apply-gc]` | Lists v2 entries not in the plan. Deletes only with `--apply-gc`, only under v2, then removes empty dirs. Never walks the source. |

## Plan rules

- Packs: `status IN (resolved, materialized)` (plus `provisional` with the flag). Category
  outside the closed list or NULL → `Misc` (counted). Folder = sanitized pack name, or
  `pack-<id>`; a case-insensitive clash with an earlier pack gets ` [<id>]`.
- Files: union of `mesh|image|doc` blobs over (1) the pack's `pack_containers`, each container
  **including its nested descendants**, and (2) the pack's loose units (below), deduplicated by
  blob. macOS debris (`__MACOSX/`, `._name`) is skipped. A `pack_containers` row means "this whole
  container belongs to the pack": a `loose_batch` listed there contributes all of its files, and
  SPEC-010 lists a batch only when every one of its files belongs to that single pack.
- **Loose units (split batches):** a batch whose files belong to several packs (or to none) is
  *not* in `pack_containers`; its exact membership lives in `pack_units` (`kind = 'loose'`,
  `pack_id`, `role`) + `pack_unit_sources(unit_id, source_file_id)`. For every present loose unit
  with `pack_id` set, each `pack_unit_sources` source file contributes its loose-batch occurrence
  (`member_chain = [source path]`) to that unit's pack, with the **unit's role** feeding the same
  role priority below (`primary` > `source` > `absorbed`; every role is planned — `absorbed`
  units are attached previews/img.zip content, not exclusions). The same source file may sit in
  units of several packs: it is planned into each of them (one blob, one store inode, hardlinked
  from the source). Dedupe-by-blob, path layout, sanitization, collision naming and the
  hardlink-from-source rule are identical to whole-batch files; the plan stores the batch
  container, the source path and `member_chain` as provenance and lists the units in the pack's
  `meta.loose_units` (also `forge.source_loose_units[]` in `datapackage.json`).
  A file reachable both ways for one pack (batch in `pack_containers` and in that pack's unit
  sources) is planned once, through the container, with the container's role.
  Archive units are never read here: they are planned through their `pack_containers` row.
- **Unassigned units:** a present loose unit with `pack_id IS NULL` (the resolver put no pack on
  it) is skipped — never guessed into a pack — and reported in the plan totals as
  `unassigned_loose_units`, `unassigned_loose_files` and `unassigned_loose_unit_sample` (first 20
  unit keys). The counts cover the whole catalog, not only `--pack` selections.
- Path: from the pack's best occurrence (role primary > source > absorbed, then shallowest, then
  path). Relative to the common directory of the pack's anchors (archive file / loose file);
  nested archives become folders without their suffix (`mid.zip/inner.7z/x.stl` →
  `mid/inner/x.stl`); with more than one source archive in the pack, each archive's members sit
  under the archive's stem. `--layout flat` keeps basenames only.
- Sanitization (`paths.py`): NFC; control chars, `/`, `\` → `_`; `.`/`..`/empty → `_`; leading
  `.` → `_` (dot names are invisible to Manyfold); ≤ 255 UTF-8 bytes per component (stem
  truncated, `~<hash8>` added, extension kept); whole relative path ≤ 3800 bytes else
  `_long/<sha16><ext>`.
- Collisions (case-insensitive, incl. `datapackage.json` and file-vs-directory): later
  candidates get `~<sha8>` (then 16, then 64) before the extension; a parent-directory clash
  moves the file to `_conflict~<sha16><ext>`. Deterministic: a name never depends on order.
- Source per blob (global): a present loose source file of the right size → `loose` (hardlink);
  else an archive member → `archive` (prefer roots that finished `done`, then shallowest, then
  smallest container); else `missing` (shortage, counted, never invented). Sources whose volume
  files are `present = false` are not used.
- Work units: one per source archive (all its needed members in one pass); loose blobs in
  chunks of 2000.

## Apply

Claims come from `materialize_units` / `materialize_packs` with `FOR UPDATE SKIP LOCKED`; many
processes and pods can run at once. A heartbeat refreshes `claimed_at`; a claim older than
`FORGE_MATERIALIZE_STALE_SECONDS` (900) is reaped back to `pending` (or `failed` after
`FORGE_MATERIALIZE_MAX_ATTEMPTS`, 3). `--resume` treats every claim as dead — use it only when no
other apply is running.

1. **loose units** — re-`stat` the source (size + mtime must equal the catalog, else
   `source_changed`), `link(source, store)`. `EEXIST` with the right size → `existing`.
2. **archive units** — re-`stat` every volume; blobs already in the store are `existing` without
   reading; otherwise one sequential pass (`extract.py`) over the container with the engine's own
   readers and name rules (so chains match the catalog, including `//dupN`): libarchive
   (multi-volume), gzip/bzip2/xz stream, and the 7zz fallback under the same condition the
   engine uses. Wanted members stream into `.forge-blobs/<aa>/<bb>/tmp-u<unit>-*` (`O_EXCL`),
   are fsync'ed, and are published only if sha256 **and** size match (`link(tmp, final)`, then
   the temp name is removed; a mismatch removes the temp and records `sha_mismatch`). Nested
   archives on the path to a wanted member are spooled to scratch, checked against the nested
   container's catalog sha, and recursed. Nothing else is extracted. Caps from `FORGE_CAP_*`
   (wall time, member size, spool) still apply.
3. **packs** — claimable once none of its blobs is `pending`. Each file: already the store inode
   → `skipped`; an identical copy → `skipped`; missing → `link(store, target)`; wrong → temp name
   + `rename()`. `datapackage.json` is rewritten only if its content (ignoring
   `materialized_at`) changed. Status `done`, or `incomplete` when some blob failed/missing
   (listed in `datapackage.json` → `forge.missing`).

**Hardlinks from a non-root pod:** with `fs.protected_hardlinks=1` (the node default) the kernel
only lets a UID hardlink a file it owns or may read *and write*. Source files are owned by the
Synology users (UID 1024/1026, GID 100); mode-666 files link from any UID, 644 files only from
their owner. `preflight` shows the split; pick the Job's `runAsUser` accordingly. Files that
cannot be linked are copied (verified), so the result is correct either way — only slower and
larger.

**Copy fallback:** if `link()` fails with `EXDEV/EPERM/EACCES/ENOTSUP/EMLINK`, a verified copy is
written (temp + sha check + rename) and counted (`method=copied`). `--no-copy-fallback` turns
that into a failure. `preflight` tells you in advance.

**Resume:** a killed attempt leaves at most one stale claim and some `tmp-u<unit>-*` /
`.forge-tmp-*` names; the next attempt of that unit/pack removes exactly those, and published
files are skipped. `test_ac3_kill_mid_apply_then_resume_gives_identical_tree` SIGKILLs a real
`forge materialize apply` process at three different points and compares tree hashes with an
uninterrupted run.

## datapackage.json

Frictionless-style: `name` (slug), `title`, `category`, `creator`, `source`, `keywords`,
`resources[]` (`path`, `bytes`, `hash: "sha256:<hex>"`, `forge_kind`, `provenance`
{`container_id`, `source_path`, `member_chain`}, `materialized_from` {`kind: loose`, `path`} or
{`kind: archive`, `container_id`, `member_chain`}), and `forge` {`pack_id`, `plan_id`, `tool`,
`tool_version`, `materialized_at`, `needs_review`, `classified`, `pack_status`,
`source_containers[]` (id, role, kind, source paths), `source_loose_units[]` (unit_id, unit_key, path, role), `blob_shas[]`, `missing[]`}.

## State tables (Alembic `0005_materialize`)

`materialize_plans` (append-only; one `active`), `materialize_units` (claim table),
`materialize_blobs` (per plan: size, kind, chosen source, unit, state/method/error),
`materialize_packs` (dir, counts, status, meta snapshot), `materialize_files` (pack × relative
path → blob + provenance). Catalog ids are plain columns (no FKs into the catalog), so a
re-sweep can never be blocked by an old plan.

## Running it for real (in-cluster Job, never from the control node)

Templates live in `home_k3/apps/manyfold/manifests/forge/materialize/` as `.yaml.tmpl` so ArgoCD
never applies them; that README has the exact commands. The Job mounts the Backups export root
once at `/nas` (`/nas/3D-Prints` source, `/nas/3D-Prints-v2` v2) so `link(source, v2)` is legal.

Order: sweep finished → packs/classify decided → `plan` (record totals, owner gate
`bulk_data_mutation`) → `preflight` → `apply --pack <one>` + `verify --all` smoke → full
`apply` → `verify --all` → `audit-source` (and the orchestrator's source walk diff = 0).
