# Task Plan: Fix manyfold-ai scanner issues

## Goal

Fix filesystem discovery so library scans find deep trees and new files in existing models; harden locks/scan state, Federails batching, and NFS efficiency. Stay on manyfold-ai `main` only.

## Phases

| Phase | Status | Notes |
|-------|--------|-------|
| 0 Planning files | complete | task_plan / findings / progress |
| 1 Discovery correctness | complete | deep recurse, known-file deltas, symlinks, specs |
| 2 Reliability | complete | lock_ttl, scan_started_at clear, create race |
| 3 Federails / scan batch | complete | Followable + actor skip |
| 4 NFS efficiency | complete | refresh once, CheckMissingFilesJob, light problems |
| 5 Analyse undigested | complete | job + rake |
| 6 Ship | complete | pinned 1ad48b66; Synced/Healthy; scan draining |

## Decisions

- Depth: recurse under unknown dirs (max depth 6 via SCAN_MAX_DEPTH); do not require spark-curate.
- Keep SCAN_DEFER_ANALYSIS=1; Phase B is AnalyseUndigestedJob.
- Never full-library Dir.glob("**/*") into memory.

## Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| No local ruby/docker for rspec | 1 | Rely on GH Actions CI after push |
