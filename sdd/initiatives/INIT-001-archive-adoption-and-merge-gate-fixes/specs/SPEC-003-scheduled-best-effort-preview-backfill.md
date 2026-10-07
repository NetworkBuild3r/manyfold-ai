# SPEC-003 · Scheduled: Best-effort preview backfill in scan jobs

## Metadata

```yaml
spec_id: SPEC-003
initiative_id: INIT-001
title: Best-effort, error-isolated preview backfill in CheckForProblems and HealMissingPreviews
domain: scheduled
status: ready
primary_prompt: .claude/agents/principal-backend-developer/AGENT.md   # agents dir absent — described persona (disclosed)
supplement_prompts: []
model: sonnet
autonomy_level: auto_tests
gate_actions: []
reversibility_class: branch
security_review: light
estimated_effort: 3 hours
blocked_by: [SPEC-002]
blocks: None
```

---

## Description

**Context (MAJ-3):** `Archive::EnsurePreview` rescues only three error classes, so any other failure
escapes. Examples: an archive read error, MiniMagick, `SystemCallError`, `RecordInvalid`. The escaped
error:
- aborts every later problem detector in `CheckForProblemsJob`;
- aborts the whole `HealMissingPreviewsJob#heal_nil_previews` batch.

`EnsurePreview` also retries failed entries forever and can be blocked by one oversized "cover" image
(MIN-1, same method).

**Scope (in):** `app/services/archive/ensure_preview.rb`, `app/jobs/scan/model/check_for_problems_job.rb`,
`app/jobs/scan/model/heal_missing_previews_job.rb`, and specs.

**Scope (out):** Adoption internals (SPEC-002).

## Understood

- [ ] und-1: Preview backfill is best-effort. It must never stop problem detection or a heal batch.

## Acceptance Criteria

- [ ] ac-1: `EnsurePreview#call` rescues `StandardError` after the three typed rescues, logs
  `[EnsurePreview] model=<id> <class>: <message>`, and returns `nil`. — covered: no
- [ ] ac-2: If `ensure_image_preview!` raises inside `CheckForProblemsJob`, every subsequent detector still
  runs. A spec stubs it to raise and asserts that `Problems::NoImage` / `NoLicense` / `MissingFile` were
  invoked. — covered: no
- [ ] ac-3: `heal_nil_previews` continues past a model whose backfill raises. A spec with 3 models where the
  2nd raises heals models 1 and 3, and the job returns the correct `healed` count. — covered: no
- [ ] ac-4: The new archive-only branch in `heal_nil_previews` is tested: it heals once, counts once, and
  calls `check_for_problems_later`. — covered: no
- [ ] ac-5 (MIN-1): `best_archive_image` selects from `ArchiveEntry.adoptable`, excludes `preview_failed`
  and entries over `SiteSettings.max_file_extract_size`, and still prefers preview/cover/thumb names among
  the eligible entries. — covered: no

## Assumptions Ledger

| id    | item | interpretation | tone | resolved |
| ----- | ---- | -------------- | ---- | -------- |
| aud-1 | Inline vs enqueued archive extraction in `CheckForProblemsJob` | Enqueue `PreviewArchiveEntryJob` for the chosen entry instead of extracting inline, so the `:scan` queue stays light | clear (owner: defaults, 2026-10-07) | yes |

## Deliverables

- [ ] `app/services/archive/ensure_preview.rb`
- [ ] `app/jobs/scan/model/check_for_problems_job.rb`
- [ ] `app/jobs/scan/model/heal_missing_previews_job.rb`
- [ ] Tests: `spec/jobs/scan/model/check_for_problems_job_spec.rb`,
  `spec/jobs/scan/model/heal_missing_previews_job_spec.rb`, `spec/services/archive/ensure_preview_spec.rb` (new)

## Gates & Controls

- **Gate actions:** none.

## Security

- **Sensitivity:** light. Log lines must not include file contents.

## Verification Strategy

- **Claim:** A backfill failure never prevents problem detection or the rest of a heal batch, and
  candidate selection skips ineligible entries.
- **Check + executor:** mechanized: `bundle exec rspec spec/jobs/scan/model spec/services/archive/ensure_preview_spec.rb`
  plus `bundle exec rake rubocop`, in the CI DB matrix.
- **Pass condition:** The ac-2 and ac-3 failure-injection specs pass and would fail if the rescue were
  removed (the author demonstrates this once by reverting the rescue locally). The ac-5 selection specs
  cover `preview_failed`, oversize and `dismissed` exclusion.

## Integration Points

- Consumes `ArchiveEntry.adoptable` (SPEC-001) and hardened adoption (SPEC-002).
- **Change:** error isolation for preview backfill in scan jobs.
- **Provenance tag:** `INIT-001/SPEC-003`
