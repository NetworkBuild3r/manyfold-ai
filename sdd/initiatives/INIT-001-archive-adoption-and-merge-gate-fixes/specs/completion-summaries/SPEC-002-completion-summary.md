# SPEC-002 Completion Summary — Safe, idempotent, isolated image adoption

**Provenance:** `INIT-001/SPEC-002` · **Completed:** 2026-10-07 · **Findings closed:** CRIT-1 (re-scoped by owner), MAJ-1, MAJ-2, MAJ-6 (adoption part), MIN-2

## Changes
- `app/services/archive/adopt_image.rb`:
  - The class doc states the every-image policy.
  - New `entry:` keyword: a dismissed entry is skipped, and the entry is linked to the file it resolved to
    (created or digest-matched, per the aud-2 default).
  - Bytes are staged into `model/.manyfold/tmp/` outside the lock. Match, name, rename into place and
    `create!` run inside `@model.with_lock`. If `create!` fails, the placed file is removed. The staged
    copy is always cleaned up.
  - `matching_image` ignores records whose file is not on storage.
- `app/services/archive/preview_entry.rb`: the thumbnail is written **before** adoption. Adoption errors
  (`SystemCallError`, `RecordInvalid`, `RecordNotUnique`) are logged and swallowed. `enqueue_previews!`
  skips `ArchiveEntry::NOT_ADOPTABLE_STATUSES` (now including `dismissed`).
- `app/jobs/scan/model_file/preview_archive_entry_job.rb`: returns early for `dismissed` entries, so the
  tombstone is never overwritten.
- `spec/services/archive/adopt_image_spec.rb` (new, 12 examples) and 2 new examples in
  `spec/services/archive_entry_service_spec.rb` (thumbnail survives an adoption failure; dismissed entries
  are not re-previewed).

## Deviation from the spec text (ac-4)
The spec said "renamed only after `create!` succeeds". `ModelFile`'s `after_create` attaches the file from
its final path, so the file must exist before `create!`. Instead the rename and `create!` run under the
same model lock, and a failed `create!` deletes the renamed file. The guarantee is unchanged: no orphan
file and no name race.

## Verification
- Docker `test` (PostgreSQL 17): `rspec` over adopt_image, archive_entry_service, archive_entry,
  check_for_problems_job and heal_missing_previews_job specs: 58 examples, 6 failures. All 6 also fail on
  the untouched baseline:
  - 3 are mesh-thumbnail tests (`archive_entry_service_spec.rb:161/232/246`);
  - 3 are `heal_missing_previews_job_spec.rb:24/34/45`, in the broken-preview path, which this spec does
    not touch.
- `rubocop` on new and changed files: no new offences. `preview_entry.rb` keeps 3 pre-existing offences
  in the mesh code.
- **Declared unmechanized:** true multi-thread interleaving. The spec asserts that `with_lock` is used,
  and a reviewer confirms that its block covers the whole match-to-create sequence.
- **Not yet verified:** the SQLite and MySQL CI jobs.
