# SPEC-002 · Service: Safe, idempotent, isolated image adoption

## Metadata

```yaml
spec_id: SPEC-002
initiative_id: INIT-001
title: Safe, idempotent, isolated archive image adoption
domain: service
status: complete
primary_prompt: .claude/agents/principal-backend-developer/AGENT.md   # agents dir absent — described persona (disclosed)
supplement_prompts: []
model: sonnet
autonomy_level: auto_tests
gate_actions: []
reversibility_class: branch
security_review: standard
estimated_effort: 5 hours
blocked_by: [SPEC-001]
blocks: [SPEC-003, SPEC-004]
```

---

## Description

**Context:** The review found that the current adoption code has four problems:
- CRIT-1: every image entry is adopted. The owner has now confirmed this is intended, but it was neither
  documented nor traceable.
- MAJ-1: adoption runs before the thumbnail is written, so any adoption failure kills the thumbnail.
- MAJ-2: concurrent preview jobs race on filename and digest, overwriting different images.
- MAJ-6: the paths above are untested.

**Scope (in):** `Archive::AdoptImage`, its call site in `Archive::PreviewEntry#extract_preview_image!`,
the provenance link write (SPEC-001), and specs.

**Scope (out):** Scan-job error isolation (SPEC-003), archive rewrite on delete (SPEC-004).

## Understood

- [x] und-1: **Every** image entry in an archive is adopted onto its model (owner decision, 2026-10-07). This
  is policy, not a bug. CRIT-1 is resolved by making adoption idempotent, traceable and failure-isolated.
- [x] und-2: Adoption must never block or fail the archive thumbnail.
- [x] und-3: An existing on-disk image preview is never replaced by adoption.

## Acceptance Criteria

- [x] ac-1 (CRIT-1): The `AdoptImage` class doc states the every-image policy. An archive with N distinct
  images yields exactly N adopted ModelFiles. Running the preview pass a second time adds 0 files. —
  covered: no
- [x] ac-2 (CRIT-1): Each adopted or digest-matched file is linked back via
  `entry.update!(adopted_model_file: file)`. A `dismissed` entry is never adopted. — covered: yes
- [x] ac-3 (MAJ-1): `extract_preview_image!` writes the thumbnail **before** adopting. An adoption failure is
  logged with the entry id and the entry still ends `preview_ready`. Failures covered:
  `SystemCallError`, `ActiveRecord::RecordInvalid`, `ActiveRecord::RecordNotUnique`. — covered: yes
- [x] ac-4 (MAJ-2): Match → name → copy → create runs inside `@model.with_lock`. Bytes are copied to a temp
  name in the model folder and renamed only after `create!` succeeds. A failed `create!` leaves no file on
  disk. — covered: yes
- [x] ac-5 (MAJ-2): Two entries with the same basename and different bytes produce two files (`x.png`,
  `x-1.png`), each with the correct digest of its own bytes. Two entries with the same bytes produce one
  file. — covered: yes
- [x] ac-6 (MIN-2, same lines): `matching_image` ignores ModelFiles that are not `exists_on_storage?`. —
  covered: no
- [x] ac-7 (MAJ-6): Every criterion above has a spec example. The existing three examples in
  `spec/services/archive_entry_service_spec.rb` still pass. — covered: yes

## Assumptions Ledger

| id    | item | interpretation | tone | resolved |
| ----- | ---- | -------------- | ---- | -------- |
| aud-1 | Adoption scope | Every image, always; no site setting (owner, 2026-10-07) | clear | yes |
| aud-2 | Link for a *matched* pre-existing loose image | Link it too, so deleting that file also removes the image from the archive (SPEC-004) | clear (owner: defaults, 2026-10-07) | yes |
| aud-3 | Lock granularity | Per-model row lock (`with_lock`), not a global advisory lock | clear (owner: defaults, 2026-10-07) | yes |

## Deliverables

- [x] `app/services/archive/adopt_image.rb`: lock, temp-then-rename, link, dismissed skip, storage check,
  class doc
- [x] `app/services/archive/preview_entry.rb`: thumbnail first, isolated adoption with `entry:` passed
- [x] Tests: `spec/services/archive_entry_service_spec.rb` (extend) and/or a new
  `spec/services/archive/adopt_image_spec.rb`

## Technical Requirements

- [x] Keep the SHA-512 chunked hashing identical to `ModelFile#calculate_digest`.
- [x] Keep `unique_filename` basename-only; do not weaken path safety.
- [x] `rubocop` clean, matching the surrounding service style (no new comment density beyond the class doc).

## Gates & Controls

- **Gate actions:** none (branch-only code change).

## Security

- **Sensitivity:** standard. Triggers: external input (archive filenames and bytes written into the library).
- **Security acceptance criteria:**
  - [x] An adopted filename is always a single path segment under `library/model/`. A spec feeds
    `../evil.png` and `a/../../b.png` entry names and asserts the destination.
  - [x] Temp files are created in the model folder (same filesystem for atomic rename) and removed on
    every failure path.

## Verification Strategy

- **Claim:** Adoption is idempotent, traceable, path-safe and failure-isolated from thumbnails (ac-1 … ac-7).
- **Check + executor:**
  - mechanized: `bundle exec rspec spec/services/archive_entry_service_spec.rb spec/services/archive/`
    plus `bundle exec rake rubocop`, in the CI DB matrix.
  - human: a reviewer confirms that the `with_lock` block encloses the full match → create sequence. True
    multi-thread interleaving is **declared unmechanized**, because this repo has no concurrency test
    harness.
- **Pass condition:** All examples pass on SQLite, MySQL and PG. Specs exist for: multi-image (N files,
  then 0 on re-run), same-basename/different-bytes, same-bytes/different-path, read-only destination
  (thumbnail still written), `create!` failure (no orphan), existing preview untouched, dismissed skipped,
  link recorded, and path-traversal names. The reviewer signs off that the lock scope is right.

## Integration Points

- SPEC-004 relies on the `adopted_model_file` link this spec writes.
- **Change:** hardened adoption plus a provenance write.
- **Provenance tag:** `INIT-001/SPEC-002`
