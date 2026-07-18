# Findings: Scanner issues

## Critical

1. `DetectFilesystemChangesJob#folders_with_changes` (filesystem) only returns unknown folders — new files in known models never discovered by Library Scan.
2. `new_model_folders_streaming` hard-capped at depth 2 — Cults3D/Creator/Model never indexed.

## High

3. Scan jobs `unique :until_executed` without `lock_ttl` — OOM/hang bricks rescans.
4. `scan_started_at` cleared mainly via Finalize — stuck on failure.
5. Federails Followable ignores `Current.scan_batch_id`; actors still created when federation off.

## Medium

6. Double attach/refresh on NFS during scan.
7. Missing-file pass O(all known files) inside Detect.
8. CreateModel `RecordNotUnique` race across batches.

## NFS layout (cluster)

- Mount: `/models` → Synology 3D-Prints
- Categories: Anime, Cults3D, …; Cults3D often deeper than Category/Model
