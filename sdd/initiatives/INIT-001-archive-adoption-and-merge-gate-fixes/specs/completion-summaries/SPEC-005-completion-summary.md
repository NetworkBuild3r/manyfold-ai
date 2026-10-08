# SPEC-005 Completion Summary — Model-page delete UX for archive-adopted images

**Provenance:** `INIT-001/SPEC-005` · **Completed:** 2026-10-07

## Changes
- `app/helpers/model_files_helper.rb`: `delete_confirmation_for(file)`.
  - Files with no source archives get the plain confirmation.
  - Otherwise the confirmation is extended with "This also removes X from A.zip. This cannot be undone."
    for writable archives, and/or "B.rar cannot be rewritten, so X will be hidden here but stays inside it."
  - Writability (`Archive::RemoveEntries.writable?`) is memoized per render, per archive.
- `app/views/models/_file.html.erb` and `app/views/model_files/show.html.erb` use the helper for the delete
  confirm.
- `config/locales/model_files/en.yml`: `confirm_archive_remove`, `confirm_archive_keep`. Other locales fall
  back to English until translated.
- `spec/helpers/model_files_helper_spec.rb`: plain, writable, unwritable, and memoization examples.

## Verification
- Docker `test`: helper spec examples all pass.
  - `spec/requests/model_files_spec.rb`: 2 failures, identical on baseline (signed-ID download).
  - `spec/requests/models_spec.rb`: 42 failures, the identical set on baseline (diffed).
- `rubocop` on the helper: clean. `erb_lint` on both views: clean. `i18n-tasks missing -l en` and
  `unused -l en`: clean.
- **Pending (human):** the owner clicks delete on an adopted image in dev and reads the dialog.

## Note
- `i18n-tasks normalize` was run once by mistake and rewrote unrelated locale files. Those changes were
  reverted before commit; only the two new keys are included.
