# SPEC-003 Completion Summary — Best-effort preview backfill in scan jobs

**Provenance:** `INIT-001/SPEC-003` · **Completed:** 2026-10-07 · **Findings closed:** MAJ-3, MAJ-6 (job part), MIN-1

## Changes
- `app/services/archive/ensure_preview.rb`:
  - Never raises. Any error is logged as `[EnsurePreview] model=<id> <class>: <msg>` and returns `nil`.
  - Archive extraction is no longer inline (aud-1 default). It marks the chosen entry `preview_pending`
    and enqueues `PreviewArchiveEntryJob`, whose adoption assigns the preview. Returns `:assigned`,
    `:enqueued` or `nil`.
  - Candidates come from `ArchiveEntry.adoptable`, unadopted and not `preview_failed`, with size ≤
    `max_file_extract_size`. Preview/cover/thumb names are still preferred.
- `app/jobs/scan/model/heal_missing_previews_job.rb`: the archive branch counts a queued adoption as
  healed, and a per-model rescue keeps the batch going. `check_for_problems_later` follows from the adopted
  ModelFile's `after_commit`, not from this job (ac-4 is satisfied through that path).
- `CheckForProblemsJob` is unchanged. Its `ensure_image_preview!` call can no longer raise, because
  `EnsurePreview` rescues internally.
- Specs:
  - new `spec/services/archive/ensure_preview_spec.rb` (5 examples);
  - `check_for_problems_job_spec.rb`: the remaining detectors still run when backfill fails;
  - `heal_missing_previews_job_spec.rb`: 3 archive-only models where the 2nd raises give `healed == 2`;
  - `archive_entry_service_spec.rb`: the scanner-backfill example now performs the enqueued job.

## Verification
- Docker `test` (PostgreSQL 17): `rspec spec/services/archive spec/services/archive_entry_service_spec.rb spec/jobs/scan/model`
  gives 136 examples, 22 failures. All 22 also fail on the untouched baseline:
  - 3 mesh-thumbnail examples;
  - 3 heal broken-preview examples;
  - 16 in `add_new_files_job_spec.rb` / `parse_metadata_job_spec.rb`.

  Every new example passes.
- `rubocop` on changed files: no offences.
- **Not yet verified:** the SQLite and MySQL CI jobs.
