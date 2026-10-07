# SPEC-004 Completion Summary — Remove adopted images from their source archives

**Provenance:** `INIT-001/SPEC-004` · **Status:** in_review (merge gate: owner review of the rewrite code) · **Date:** 2026-10-07

## Changes
- `app/services/archive/remove_entries.rb` (new): `Archive::RemoveEntries.call(model_file:, pathnames:)`.
  - Detects format and filter from the first header. Writable: zip, tar (any variant) and 7z; tar may use
    none/gzip/bzip2/xz, while zip and 7z must have no outer filter. Anything else is `:unwritable`: RAR,
    unreadable archives, or a non-filesystem library.
  - Streams every kept entry (header + data) into `.<name>.<hex>.rewrite` beside the original.
  - Re-reads the temp file and requires its entry list to equal the kept list.
  - Copies the original file mode, then `File.rename`s over the original. The temp file is always removed.
  - `RemoveEntries.writable?(model_file)` is exposed for SPEC-005.
- `app/jobs/scan/model_file/remove_archive_entries_job.rb` (new):
  - `unique :until_executing`, so a deletion during a running rewrite still queues a follow-up. The rewrite
    runs under the archive's row lock.
  - Removes **all** dismissed entries of the archive in one rewrite.
  - On success it deletes the removed entries' rows and `.manyfold` derivative/cache dirs, refreshes the
    archive's attachment metadata, digest and listed count.
  - On `:unwritable` it records an `error_message` and leaves the entries dismissed.
- `app/models/model_file.rb`: `delete_from_disk_and_destroy` first dismisses linked entries in archives of
  the **same model**, then deletes the file and row as before, then enqueues one job per source archive.
  `adopted_source_archives` is added for SPEC-005.

## Verification
- Docker `test` (PostgreSQL 17, libarchive 3.8.5): `rspec spec/services/archive spec/jobs/scan/model_file spec/models/model_file_spec.rb spec/models/archive_entry_spec.rb`
  gives 92 examples, 0 failures. That includes real rewrites of zip, tar.gz and 7z; failure injection
  (writer raising mid-stream, verify failing), with the original's SHA-512 unchanged and no temp file
  left; s3 and fake-RAR unwritable; mode preserved; one job per archive; cross-model archives never
  touched; the no-link delete regression.
- `spec/models/model_spec.rb` has 25 failures, identical on the untouched baseline (merging, activity,
  permissions). No new failures.
- `rubocop` on changed and new files: no offences.

## Outstanding before merge (gate)
- **Owner review** of `remove_entries.rb` and the job.
- **Manual check:** delete one adopted image from a real zip on a dev library, then open the archive in an
  external tool.
- The SQLite and MySQL CI jobs.
- `complete-initiative` Phase 3.5 security review (`security_review: required`).

## Known limits
- Encrypted or multi-volume archives surface as an `Archive::Error` during the rewrite. The job fails and
  the original is untouched, but the entry stays dismissed with no `error_message`. Follow-up: map that
  error to the unwritable message.
