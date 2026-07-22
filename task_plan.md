# Task Plan: Archive contents scanner

## Goal

Opt-in peek into library archives (zip/7z/rar): list entries, save previews, download single files, live WebGL for meshes — without full extract into the model folder.

## Phases

| Phase | Status | Notes |
|-------|--------|-------|
| Schema + ModelFile#is_archive? | complete | archive_entries + counters |
| ArchiveEntryService + list/preview jobs | complete | caps, EXTRACT_SECURE |
| mesh_thumbnail.mjs + MiniMagick fallback | complete | Node optional; IM placeholder default |
| Download/content/preview routes | complete | ArchiveEntriesController |
| UI panels + scan buttons | complete | model + file show |
| Rake + SiteSetting | complete | scan_archives_on_metadata default false |
| Specs + ship | in_progress | |

## Decisions

- Do not auto-scan during library discovery (scan_batch_id).
- Mesh PNG uses MiniMagick info card when Node is absent (runtime image).
- ArchiveEntry is not a ModelFile (paths under .manyfold only).

## Errors Encountered

| Error | Attempt | Resolution |
|-------|---------|------------|
| | | |
