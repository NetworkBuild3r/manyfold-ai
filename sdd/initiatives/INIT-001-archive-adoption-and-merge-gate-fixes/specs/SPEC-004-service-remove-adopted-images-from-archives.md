# SPEC-004 · Service: Remove adopted images from their source archives

## Metadata

```yaml
spec_id: SPEC-004
initiative_id: INIT-001
title: Deleting an adopted image removes it from the model and from its source archive(s)
domain: service
status: in_review
primary_prompt: .claude/agents/principal-backend-developer/AGENT.md   # agents dir absent — described persona (disclosed)
supplement_prompts: []
model: opus   # pinned: destructive, irreversible-at-runtime operation on user originals
autonomy_level: auto_tests
gate_actions: [merge]   # human review of rewrite code required before merge
reversibility_class: revertible   # code is revertible; the runtime effect on user archives is NOT — see Gates
security_review: required
estimated_effort: 6 hours
blocked_by: [SPEC-001, SPEC-002]
blocks: [SPEC-005]
```

---

## Description

**Context:** Owner requirement (2026-10-07): deleting an archive-adopted image from the model page must
remove it from the model *and* from the archive. Today `ModelFile#delete_from_disk_and_destroy` deletes
only the loose file. Because the image is still in the archive, the next scan would re-adopt it.

**Scope (in):**
- `Archive::RemoveEntries`: rewrites an archive without the given entries, using `ffi-libarchive`.
- A background job that runs the rewrite.
- A hook in `ModelFile#delete_from_disk_and_destroy`.
- Cleanup: `ArchiveEntry` rows and derivatives, and a refresh of the archive ModelFile's digest, size and
  metadata.

**Scope (out):** UI copy and flash messages (SPEC-005); deleting non-image entries; bulk "remove from
archive" without deleting.

## Understood

- [ ] und-1: Deleting the ModelFile and dismissing its linked entries happens **immediately**, in the
  request. The archive rewrite happens **asynchronously**, because archives can be gigabytes.
- [ ] und-2: An entry is dismissed before the rewrite starts. Even if the rewrite fails or the format is
  unwritable, the image is never re-adopted.
- [ ] und-3: An archive is never modified in place. The rewrite writes a temp file, verifies it, then
  atomically renames it over the original.

## Acceptance Criteria

- [x] ac-1: Deleting a ModelFile with `adopted_from_entries` deletes the loose file and the row, sets each
  linked entry to `dismissed`, and enqueues `Scan::ModelFile::RemoveArchiveEntriesJob` once per source
  archive. — covered: yes
- [x] ac-2: For writable formats (at minimum zip, 7z and tar variants libarchive can write), the job:
  1. writes a new archive in the **same format and filter** to a temp path in the same directory, copying
     every entry except the removed ones (preserving path, mtime and mode);
  2. verifies by re-reading that the entry count is the original count minus the removed count, and that
     none of the removed paths are present;
  3. `File.rename`s it over the original.

  — covered: yes
- [x] ac-3: On any failure (read error, verify mismatch, ENOSPC, EACCES) the original archive is
  byte-identical, the temp file is gone, the entries stay `dismissed`, and the error is logged. — covered: yes
- [x] ac-4: Unwritable or unsupported formats are not rewritten. This covers RAR, encrypted or multi-volume
  archives, and non-filesystem (S3) libraries. The job records `error_message: "archive format not
  writable; image hidden but kept in archive"` on the entry and returns cleanly. — covered: yes
- [x] ac-5: After a successful rewrite:
  - the removed `ArchiveEntry` rows and their preview/cache derivatives under `.manyfold/` are deleted;
  - the archive ModelFile's digest and size are recalculated and its attachment metadata refreshed;
  - other entries keep their `public_id`s.

  — covered: yes
- [x] ac-6: Deleting a ModelFile with **no** linked entries behaves exactly as today (regression spec). —
  covered: yes
- [x] ac-7: Two images removed from the same archive in quick succession produce a correct final archive.
  The job holds a per-archive lock (`unique` / `with_lock` on the archive ModelFile), so rewrites never
  interleave. — covered: yes

## Assumptions Ledger

| id    | item | interpretation | tone | resolved |
| ----- | ---- | -------------- | ---- | -------- |
| aud-1 | Image present in several archives | Remove from **every** linked archive | clear (owner: defaults, 2026-10-07) | yes |
| aud-2 | Backup of original archive | No `.bak`. Rely on atomic temp, verify, rename | clear (owner: defaults, 2026-10-07) | yes |
| aud-3 | Sync vs async rewrite | Async job; dismiss synchronously (und-1) | clear (owner: defaults, 2026-10-07) | yes |
| aud-4 | Deleting a pre-existing loose image that was digest-matched (SPEC-002 aud-2) | Also removes the image from linked archives | clear (owner: defaults, 2026-10-07) | yes |
| aud-5 | Writable format set | Whatever `Archive::Writer` supports for the detected format, probed at runtime; never hard-coded "zip only" | clear (owner: defaults, 2026-10-07) | yes |

## Deliverables

- [x] `app/services/archive/remove_entries.rb` (new)
- [x] `app/jobs/scan/model_file/remove_archive_entries_job.rb` (new; `unique :until_executed`, keyed by
  archive file id)
- [x] `app/models/model_file.rb`: `delete_from_disk_and_destroy` hook (dismiss and enqueue)
- [x] Tests: `spec/services/archive/remove_entries_spec.rb`,
  `spec/jobs/scan/model_file/remove_archive_entries_job_spec.rb`, and `spec/models/model_file_spec.rb`
  (destroy hook). Fixtures: zip and 7z built in-spec; a RAR fixture or stubbed writer-unsupported path.

## Technical Requirements

- [ ] Read with `Archive::Reader` and write with `Archive::Writer` (`ffi-libarchive`, already a runtime
  gem). Do not add `rubyzip` to runtime; it is dev/test only.
- [ ] Reuse `EntrySupport#normalize_pathname` / `unsafe_pathname?`; match removals by normalized pathname.
- [ ] Stream entry data; never buffer a whole archive in memory.

## Gates & Controls

- **Gate actions:** `merge`. A human reviews `remove_entries.rb` and the job before merge.
- **Runtime irreversibility:** at runtime this permanently modifies users' original archive files. That is
  why `security_review: required`, `model: opus`, and the merge gate apply.
- **Blocking checks:** full `bundle exec rspec` in the CI DB matrix, `rake rubocop`, and no unresolved
  Critical/High from the security review.
- **Rollback plan:** revert the commit. The destroy hook disappears, and already-rewritten archives cannot
  be restored by code (users' own backups only). This is stated in the PR description.

## Security

- **Sensitivity:** required. Triggers: destructive modification of user data from a web request;
  untrusted archive content.
- **Security acceptance criteria:**
  - [ ] A rewrite only ever targets archives that are ModelFiles of the **same model** as the deleted
    file, and authorization stays on the existing `authorize @file` in `ModelFilesController#destroy`.
  - [ ] The temp path is generated (`SecureRandom`), lives in the archive's own directory, and is never
    derived from entry names.
  - [ ] Entries whose names fail `unsafe_pathname?` are copied byte-for-byte or the rewrite aborts; they
    are never re-rooted.
  - [ ] Symlink entries are preserved as-is and never followed during the rewrite.
- **Review depth:** thorough. Focus: data, owasp (file handling).

## Verification Strategy

- **Claim:** Deleting an adopted image removes it from its writable source archives atomically, and leaves
  the archive byte-identical on any failure (ac-1 … ac-7).
- **Check + executor:**
  - mechanized: `bundle exec rspec spec/services/archive/remove_entries_spec.rb spec/jobs/scan/model_file/remove_archive_entries_job_spec.rb spec/models/model_file_spec.rb`,
    in the CI DB matrix.
  - human: the owner reviews the rewrite and verify logic before merge, and manually deletes one adopted
    image from a real zip on a dev library, then confirms the archive still opens in an external tool.
- **Pass condition:**
  - Specs prove: post-rewrite listing equals the original minus the removed entries; the failure-injected
    rewrite (stubbed writer raising mid-stream) leaves the original's SHA-512 unchanged and no temp file;
    the unsupported format leaves the archive unchanged with the entry dismissed; the no-link delete
    behaves as before.
  - The manual check passes: the archive opens and the image is absent.

## Integration Points

- Consumes SPEC-001's link and status, and SPEC-002's link writes. SPEC-005 surfaces the outcome.
- **Change:** delete-from-archive for adopted images.
- **Provenance tag:** `INIT-001/SPEC-004`
