# Task Plan: Fix blank card previews

## Goal

Stop broken card thumbnails when DB `preview_file` points at NFS paths that no longer exist. Harden serve/UI (404 + empty placeholder), heal stale preview pointers, ship on manyfold-ai `main` only.

## Phases

| Phase | Status | Notes |
|-------|--------|-------|
| A Planning files | complete | Reset task_plan / findings / progress |
| B Harden serve/UI | complete | 404 missing files; PreviewFrame empty; specs |
| C Heal previews | complete | resolve_preview_file + HealMissingPreviewsJob + rake |
| D Ship + run heal | in_progress | Pin digest, Argo sync, rake heal, verify |

## Decisions

- Heal + harden only — do not auto-delete orphan missing-folder models.
- PreviewFrame may call `exists_on_storage?` once per visible card.
- `send_file_content` returns 404 (not 500) on ENOENT / Shrine::FileNotFound.

## Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| | | |
