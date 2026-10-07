# SPEC-001 · Data: Archive-entry → adopted-file provenance + `dismissed` status

## Metadata

```yaml
spec_id: SPEC-001
initiative_id: INIT-001
title: Archive-entry to adopted-ModelFile provenance link and dismissed status
domain: data
status: complete
primary_prompt: .claude/agents/database-architect/AGENT.md   # agents dir absent — executes under described persona (disclosed)
supplement_prompts: []
model: sonnet
autonomy_level: auto_tests
gate_actions: [db_migration]
reversibility_class: revertible
security_review: light
estimated_effort: 2 hours
blocked_by: None
blocks: [SPEC-002, SPEC-004]
```

---

## Description

**Context:** Adopted images (`Archive::AdoptImage`) currently have no record of the archive entry they
came from. Without that link, deleting an image cannot remove it from its archive (owner requirement),
and a deleted image would be re-adopted on the next scan.

**Scope (in):**
- An additive migration adding a nullable `archive_entries.adopted_model_file_id` FK →
  `model_files.id` (`on_delete: :nullify`, indexed).
- A new allowed `ArchiveEntry` status `dismissed`, a tombstone meaning "never adopt or preview again".
- Associations on both models, and a `ArchiveEntry.adoptable` scope.

**Scope (out):** Writing the link (SPEC-002), archive rewrite (SPEC-004), UI (SPEC-005).

## Understood

- [x] und-1: Many entries (same image in several archives, or repeated in one archive) may point at one ModelFile.
- [x] und-2: The link must survive file *renames* (it is an id, not a filename).

## Acceptance Criteria

- [x] ac-1: The migration runs up and down cleanly on SQLite, MySQL and PostgreSQL. `db/schema.rb` shows the
  column, index and FK. — covered: yes
- [x] ac-2: `ArchiveEntry belongs_to :adopted_model_file, class_name: "ModelFile", optional: true` and
  `ModelFile has_many :adopted_from_entries, class_name: "ArchiveEntry", foreign_key: :adopted_model_file_id,
  dependent: :nullify, inverse_of: :adopted_model_file`. — covered: yes
- [x] ac-3: `dismissed` is accepted wherever `ArchiveEntry` validates or enumerates status.
  `ArchiveEntry.adoptable` excludes `dismissed`, `too_large` and `skipped`. — covered: yes
- [x] ac-4: Destroying a ModelFile nullifies its entries' links; it does not destroy them. — covered: yes

## Assumptions Ledger

| id    | item | interpretation | tone | resolved |
| ----- | ---- | -------------- | ---- | -------- |
| aud-1 | Column vs join table | Single FK on `archive_entries` (an entry adopts into at most one file) | clear | yes |

## Deliverables

- [x] `db/migrate/<ts>_add_adopted_model_file_to_archive_entries.rb`
- [x] `db/schema.rb`
- [x] `app/models/archive_entry.rb`, `app/models/model_file.rb` (associations and scope only)
- [x] Tests: `spec/models/archive_entry_spec.rb` (association, scope, nullify on destroy)

## Technical Requirements

- [x] Use `add_reference ... foreign_key: {to_table: :model_files, on_delete: :nullify}`. Do not backfill;
  existing rows stay `NULL`.
- [x] Follow the existing migration style in `db/migrate/`.

## Gates & Controls

- **Gate actions:** `db_migration` (additive and nullable; down-migration drops the column).
- **Rollback plan:** `rails db:rollback` for this one migration. There is no data loss, because the column
  is new.

## Security

- **Sensitivity:** light. No triggers matched.

## Verification Strategy

- **Claim:** The schema has the link column, index and FK on all three CI databases, and the associations
  behave as ac-2 to ac-4 state.
- **Check + executor:** mechanized: `bundle exec rails db:migrate db:rollback db:migrate` then
  `bundle exec rspec spec/models/archive_entry_spec.rb`, in CI across the SQLite/MySQL/PG matrix.
- **Pass condition:** All three DB jobs are green, and the new examples cover association read/write,
  `adoptable` exclusion of each excluded status, and nullify-on-destroy.

## Integration Points

- SPEC-002 writes `adopted_model_file`. SPEC-004 reads it to find source archives and writes `dismissed`.
- **Change:** an additive provenance column and a tombstone status.
- **Provenance tag:** `INIT-001/SPEC-001`
