# SPEC-001 Completion Summary — Archive-entry → adopted-file provenance + `dismissed`

**Provenance:** `INIT-001/SPEC-001` · **Completed:** 2026-10-07

## Changes
- `db/migrate/20261007120000_add_adopted_model_file_to_archive_entries.rb`: a nullable
  `archive_entries.adopted_model_file_id` with an index and an FK to `model_files` (`on_delete: :nullify`).
- `db/schema.rb`: dumped from PostgreSQL. Only the new column, index and FK changed.
- `app/models/archive_entry.rb`: the `dismissed` status, `NOT_ADOPTABLE_STATUSES`, the
  `belongs_to :adopted_model_file`, and the `adoptable` scope (images not too_large/skipped/dismissed).
- `app/models/model_file.rb`: `has_many :adopted_from_entries, dependent: :nullify`.
- `spec/models/archive_entry_spec.rb`: link, many-to-one, nullify on destroy, dismissed valid, adoptable scope.

## Verification
- Docker `test` service (PostgreSQL 17): `db:migrate` → `db:rollback` → `db:migrate` clean.
- `rspec spec/models/archive_entry_spec.rb spec/models/model_file_archive_spec.rb spec/services/archive_entry_service_spec.rb spec/jobs/scan/model/check_for_problems_job_spec.rb`:
  40 examples, 3 failures. All 3 failures (`archive_entry_service_spec.rb:161`, `:232`, `:246`, mesh
  thumbnail) also fail on the untouched baseline commit `2d0428775`. They come from the test container's
  mesh tooling, not from this spec.
- `rubocop` on the 4 changed files: no offenses.
- **Not yet verified:** the SQLite and MySQL CI jobs (no local runners). Confirm in CI before merge.
