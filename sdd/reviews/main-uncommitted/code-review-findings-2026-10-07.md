# Code Review: Archive image adoption + spark-curate TypeSafe merge routing

**Date:** 2026-10-07
**Reviewer:** `code-reviewer` persona, via `sdd-code-review` (executed inline — `.claude/agents/` is absent in this repo; see Review Notes)
**Target:** uncommitted working-tree changes on `main` (15 modified + 4 new source files)
**Review Depth:** standard
**Overall Assessment:** Request Changes

---

## Code Review Summary

This is a standard-depth review of two independent changes. (1) Rails: archive images are now copied into
the model folder as real `ModelFile`s and used as the preview (`Archive::AdoptImage`, `Archive::EnsurePreview`,
plus hooks in the scan jobs). (2) spark-curate: merge decisions now go to TypeSafe "Jev", and STRONG
structural pairs are no longer auto-approved. The overall assessment is **Request Changes**. The most
significant finding is CRIT-1. Adoption runs for *every* image entry in every listed archive, not once per
model, so routine archive scans write a full-size copy of each unique archive image into the user's library.

---

## Findings Summary

| ID     | Severity   | Category     | Title                                                                                  | Status |
| ------ | ---------- | ------------ | -------------------------------------------------------------------------------------- | ------ |
| CRIT-1 | Critical   | correctness  | Every archive image is copied into the library, not one preview per model              | Open   |
| MAJ-1  | Major      | correctness  | Adoption failure now breaks the pre-existing archive thumbnail                         | Open   |
| MAJ-2  | Major      | correctness  | Concurrent adoption race overwrites a different image under the same filename          | Open   |
| MAJ-3  | Major      | correctness  | Archive extraction errors escape into CheckForProblemsJob and HealMissingPreviewsJob    | Open   |
| MAJ-4  | Major      | correctness  | TypeSafe approval drops the confidence floor and ignores its own contradiction answers | Open   |
| MAJ-5  | Major      | correctness  | Jev's "human should decide" outcome is filed as a refusal                              | Open   |
| MAJ-6  | Major      | test         | Ruby adoption paths that matter most are untested                                      | Open   |
| MAJ-7  | Major      | test         | TypeSafe client and failure fallbacks untested; suite not hermetic to TYPESAFE_API_KEY | Open   |
| MIN-1  | Minor      | correctness  | best_archive_image retries failed entries and lets one oversized cover block the rest  | Open   |
| MIN-2  | Minor      | correctness  | A digest-matched but missing ModelFile is reused as the preview                         | Open   |
| MIN-3  | Minor      | architecture | STRONG pairs call Gemma then discard it when TypeSafe is unset; outage fails the run    | Open   |
| MIN-4  | Minor      | architecture | HITL docs/help now misdescribe STRONG behaviour; config docs incomplete                | Open   |
| SUGG-1 | Suggestion | architecture | Remove dead parameter and duplicated outcome computation in TypeSafe routing           | Open   |

**Totals:** 1 Critical, 7 Major, 4 Minor, 1 Suggestion

---

## Critical Issues — Must Fix

### CRIT-1: Every archive image is copied into the library, not one preview per model

**Location:** `app/services/archive/preview_entry.rb:50` (calls `app/services/archive/adopt_image.rb:26`)

**Problem:** `extract_preview_image!` now calls `Archive::AdoptImage` unconditionally. It is the per-entry
worker that `PreviewArchiveEntryJob` runs for every image entry, and `ListArchiveJob` → `enqueue_previews!`
enqueues every image in every listed archive (`preview_entry.rb:11-31`). `AdoptImage#call` creates a
`ModelFile` (copying the bytes into `library/model/`) whenever no digest match exists. The preview check
in `assign_preview!` only decides whether to *set the preview*. It never decides whether to *copy*. The
in-code intent says otherwise: `Model#ensure_image_preview!` reads "get one assigned", and the
`EnsurePreview` docstring reads "copy **one** unmatched image onto the model".

**Impact:** An archive with 300 render images makes the scanner write 300 new files into the user's
library folder and create 300 `ModelFile` rows. Each create fires `after_create` attach and
`after_commit` problem checks. This happens on the normal scan path and also for models that already
have a good on-disk preview. The library writes are persistent, the user can see them, and nothing
removes them later.

**Recommendation:** Only adopt when the model actually lacks an image preview, and keep the copy decision
out of the per-entry thumbnail worker:

```text
# Before (preview_entry.rb):
Archive::AdoptImage.call(model: @model, source_path: tmp.path, filename: entry.basename)
write_image_preview!(tmp.path, absolute)

# After:
write_image_preview!(tmp.path, absolute)
adopt_as_preview!(tmp.path, entry) if adopt
...
def extract_preview_image!(entry, adopt: false)   # EnsurePreview passes adopt: true
```

Alternatively, have `AdoptImage#call` return early when `@model.preview_file&.is_image? &&
exists_on_storage?`, before `create_image!`. In either case, add a spec with an archive holding two or
more images and a pre-existing preview, and assert that `model_files.count` does not change.

**Rationale:** This matches the Critical criterion "a logic error that produces a wrong result on a
common, non-edge-case input". On calibration, the trigger is common (every archive listing), the failure
mode is persistent writes to user data, the result is user-visible, and the cost compounds because the
files pile up across scans. If materializing every image *is* intended, that is a product decision. It
then needs an explicit opt-in and sign-off, because it changes the user's library, and should not be a
side effect of thumbnailing.

---

## Major Issues — Should Fix

### MAJ-1: Adoption failure now breaks the pre-existing archive thumbnail

**Location:** `app/services/archive/preview_entry.rb:50-51`

**Problem:** `AdoptImage` runs *before* `write_image_preview!`, inside the same block, with no isolation.
Any adoption failure aborts the thumbnail that worked before this change. Examples: `EACCES`/`EROFS` on a
read-only library mount, `ENOSPC`, `RecordInvalid` from the filename-uniqueness validation (see MAJ-2), or
a `stable_mime_type` validation failure. `PreviewArchiveEntryJob` then marks the entry `preview_failed`.

**Impact:** A secondary, optional feature (adoption) can now regress the primary feature (archive
previews) whenever the library is not writable.

**Recommendation:**

```text
# After:
write_image_preview!(tmp.path, absolute)
begin
  Archive::AdoptImage.call(model: @model, source_path: tmp.path, filename: entry.basename) if adopt
rescue SystemCallError, ActiveRecord::RecordInvalid => e
  Rails.logger.warn("[ArchiveEntryService] adopt failed entry=#{entry.id}: #{e.class}: #{e.message}")
end
```

**Rationale:** The trigger is realistic (read-only NAS mounts are common for media libraries), and the
failure is visible because previews go missing. This matches the Major criterion for an error path that
impacts unrelated state.

### MAJ-2: Concurrent adoption race overwrites a different image under the same filename

**Location:** `app/services/archive/adopt_image.rb:47-53` (`create_image!`), `:55-71` (`unique_filename`)

**Problem:** `enqueue_previews!` staggers jobs only 0.5 s apart (`DEFAULT_PREVIEW_STAGGER`), so the
preview jobs for one model routinely overlap. Two problems follow:

- **Same basename, different bytes** (for example `a/1.png` and `b/1.png`, which is common in archives).
  Both jobs pass `name_taken?("1.png")`, and both `FileUtils.cp` to the same path, so the second
  overwrites the first. The second `create!` then fails the `uniqueness: {scope: :model}` validation. The
  surviving `1.png` row records image A's digest over image B's bytes, and on retry B is adopted again as
  `1-1.png`. Image A is lost and B is duplicated.
- **Same bytes, different paths.** Both jobs miss `matching_image`, and both create, producing duplicates
  (`shot.png`, `shot-1.png`). The digest dedup this change exists for is not atomic.

`create_image!` also copies *before* `create!`, so any validation failure leaves an orphan file on disk.
The next filesystem scan then adopts it anyway.

**Recommendation:** Serialize adoption per model, for example with `@model.with_lock` around
match + name + copy + create. Copy to a temp name and rename after `create!` succeeds, or `rm_f` the
destination in a `rescue`. CRIT-1's fix (adopt only via `EnsurePreview`, once) also shrinks the window
considerably.

**Rationale:** This matches the Major criterion for a race reachable under realistic concurrency. It is
not Critical only because CRIT-1's fix removes most of the concurrent callers.

### MAJ-3: Archive extraction errors escape into CheckForProblemsJob and HealMissingPreviewsJob

**Location:** `app/services/archive/ensure_preview.rb:29-30`, `app/jobs/scan/model/check_for_problems_job.rb:15`, `app/jobs/scan/model/heal_missing_previews_job.rb:70`

**Problem:** `EnsurePreview` rescues only `EntryTooLarge`, `EntryNotFound` and `UnsafePath`. Archive
extraction, `MiniMagick`/`ImageProcessing` errors, `SystemCallError` and `RecordInvalid` all propagate:

- In `CheckForProblemsJob`, the call sits *before* `NoImage`, `No3dModel`, `NoLicense`, `NoLinks`,
  `NoCreator`, `NoTags`, `FileNaming` and the per-file `MissingFile` checks. One corrupt archive therefore
  silently stops all remaining problem detection for that model on every run.
- In `HealMissingPreviewsJob#heal_nil_previews`, the exception escapes the `find_each` loop and aborts the
  whole heal batch (up to 500 models, or the whole library with `LIMIT=0`).

The problem-check job now also does heavy synchronous I/O (archive extraction plus a full-size copy) on
the `:scan` queue, inside a job that previously only read state.

**Recommendation:** Treat preview backfill as best-effort at both call sites:

```text
# EnsurePreview#call
rescue ArchiveEntryService::EntryTooLarge, ArchiveEntryService::EntryNotFound, ArchiveEntryService::UnsafePath
  nil
rescue => e
  Rails.logger.warn("[EnsurePreview] model=#{@model.id} #{e.class}: #{e.message}")
  nil
```

Consider enqueuing the archive branch (`PreviewArchiveEntryJob` with an `adopt:` flag) instead of running
it inline in `CheckForProblemsJob`.

**Rationale:** Errors swallowed far from their cause, and a single bad input aborting a batch, both match
the Major criterion. The trigger needs one malformed archive, which a large library will contain.

### MAJ-4: TypeSafe approval drops the confidence floor and ignores its own contradiction answers

**Location:** `spark-curate/spark_curate/decide_merge.py:129-171` (`apply_typesafe_merge_answers`, especially `:135`)

**Problem:** On the TypeSafe path, `approved_for_apply=True` follows from `round(link_state.score) == 2`
alone:

- `min_merge_confidence` is accepted and immediately `del`'d. A score of 1.5 with `confidence=0.05` is
  approved.
- `same_printable_product` and `character_or_franchise_only` are requested (and paid for) but used only in
  the `reason` string. Take `score=1.6` with `character_or_franchise_only.noul=0.95` and
  `same_printable_product.noul=0.1`: Jev contradicts itself, and the pair is still approved.

Before this change, UNCERTAIN approval required vision confidence ≥ `min_merge_confidence` (0.80). Under
`MERGE_HITL=hitl_off`, an approved UNCERTAIN pair is auto-queued to `merges-pending.jsonl`
(`merge_hitl.py:96`). The README's own rule ("Two Batmans stay separate") is exactly what
`character_or_franchise_only` encodes, and the code never enforces it.

**Recommendation:**

```text
# After (inside apply_typesafe_merge_answers):
consistent = same_noul >= 0.5 and char_noul < 0.5
if outcome == "merge" and consistent and link_conf >= min_merge_confidence:
    return "merge", link_conf, target, reason, True
if outcome == "merge":
    return "merge", link_conf, target, reason + " (unconfirmed)", False
```

If "no fitted threshold" is a deliberate cookbook choice, remove the parameter, state the policy in the
README and in `hitl_off`'s help text, and still gate on the two consistency answers.

**Rationale:** This is a spec/behaviour mismatch with a destructive downstream effect (a folder merge)
under a realistic configuration (`hitl_off`). It is Major rather than Critical because the default
`hitl_all` never auto-queues.

### MAJ-5: Jev's "human should decide" outcome is filed as a refusal

**Location:** `spark-curate/spark_curate/decide_merge.py:165-166`, consumed at `spark-curate/spark_curate/apply_merges.py:66-68`

**Problem:** Level 1 of `MERGE_TYPESAFE_LEVELS` tells Jev that choosing it means "a human should decide
whether to merge". The code then maps it to `decision="keep_separate"`, so `classify_hitl_band` returns
`REFUSE`. `write_merge_plans` counts it as `kept`, and it never gets a `MERGE?` line in the run log, which
is the human-review surface. The only trace is a `" (curator)"` suffix in `reason` and the
`typesafe_outcome` field in the JSONL.

**Impact:** The pairs Jev flags as needing a human are the ones least likely to reach a human. They are
indistinguishable from confident refusals in counts and logs.

**Recommendation:** Keep `decision="merge"` with `approved_for_apply=False` for the curator outcome, so
it lands in the UNCERTAIN band and the `MERGE?` log like other plans. Or add an explicit `review` decision
and log it. Also count curator outcomes in `merge-summary-*.json`.

**Rationale:** A silent drop of a signal the system itself asked for matches the Major criterion
"swallows a failure silently instead of propagating it".

### MAJ-6: Ruby adoption paths that matter most are untested

**Location:** `spec/services/archive_entry_service_spec.rb:288-334`, `spec/jobs/scan/model/check_for_problems_job_spec.rb:40-51`

**Problem:** The new specs cover the happy path well, but by reading the tests these paths have none:

- Adoption when the model **already has an image preview**, or when an archive holds **two or more**
  images. This gap is what let CRIT-1 through.
- `unique_filename` collision (an on-disk file with the same name and a different digest → `shot-1.png`).
- The lazy-digest branch of `matching_image` (existing images with `digest: nil`).
- The new `HealMissingPreviewsJob#heal_nil_previews` archive branch.
- `EnsurePreview`'s rescue path, `name_rank` ordering, and failure inside `CheckForProblemsJob`. The test
  should assert that the remaining detectors still run.

**Recommendation:** Add those specs. The first one (archive with 3 images + existing preview →
`model_files.count` unchanged) should be written before the CRIT-1 fix, so it fails first.

**Rationale:** This matches the Major criterion "meaningful new/changed logic with no corresponding test",
on a code path that writes to user data.

### MAJ-7: TypeSafe client and failure fallbacks untested; suite not hermetic to TYPESAFE_API_KEY

**Location:** `spark-curate/spark_curate/typesafe_client.py:20-26`, `spark-curate/tests/test_typesafe_merge.py`, `spark-curate/tests/test_decide_merge.py`, `spark-curate/tests/test_merge_candidates.py`

**Problem:**

- `typesafe_client.py` has no tests: HTTP error mapping, `URLError`, non-JSON, a missing `answers` key.
- The `except` branch at `decide_merge.py:435-441` has no test. That branch covers a STRONG pair being
  downgraded to pending, and an UNCERTAIN pair silently falling back to the old Gemma→Qwen path with its
  0.80 threshold.
- The UNCERTAIN + previews + **vision failure** path is untested, and so is `smoke()`'s new TypeSafe check.
- `api_key_from` falls back to `os.environ["TYPESAFE_API_KEY"]`. Only 3 tests patch it. Any other test
  that reaches the TypeSafe branch (for example `test_one_mesh_plus_name_is_uncertain_calls_gemma`) makes
  a **live, billable call** with fixture data when the key is exported. That includes running inside the
  container, where `docker-compose.yml` injects the key. Results then depend on the network.

**Recommendation:** Add a module-level `setUpModule`/`autouse` patch (or `patch.dict(os.environ,
{"TYPESAFE_API_KEY": ""})`) in all three merge test modules. Add unit tests for `system_one` using a fake
`urlopen`, and one test per fallback branch.

**Rationale:** The fallback branches decide whether a merge is approved, which makes this meaningful
untested logic. Non-hermetic tests also escalate the risk.

---

## Minor Issues — Consider Fixing

### MIN-1: best_archive_image retries failed entries and lets one oversized cover block the rest

**Location:** `app/services/archive/ensure_preview.rb:37-41`

**Problem:** The query excludes only `too_large`/`skipped`, so a `preview_failed` entry is retried on
every `CheckForProblemsJob` run. `name_rank` also sorts before size. A `cover.png` larger than
`SiteSettings.max_file_extract_size` therefore wins the `min_by`, raises `EntryTooLarge` (rescued →
`nil`), and smaller valid images are never tried.

**Recommendation:** Add `.where.not(status: "preview_failed")` and
`.where("archive_entries.size <= ?", SiteSettings.max_file_extract_size)`, or iterate candidates in rank
order until one succeeds.

### MIN-2: A digest-matched but missing ModelFile is reused as the preview

**Location:** `app/services/archive/adopt_image.rb:33-35`, `:74-80`

**Problem:** `matching_image` returns a `ModelFile` with the same digest without checking
`exists_on_storage?`. If that file was deleted from disk but its row still exists, no copy is made and
`preview_file` is set to a missing file. `EnsurePreview` then repeats the work on every scan without ever
healing it. A matched (not created) file also doesn't fire `check_for_problems_later`, so `NoImage` can
stay stale on the heal path.

**Recommendation:** Filter matches with `exists_on_storage?`. Call `@model.check_for_problems_later` after
`assign_preview!` changes the preview.

### MIN-3: STRONG pairs call Gemma then discard it when TypeSafe is unset; outage fails the run

**Location:** `spark-curate/spark_curate/decide_merge.py:388-405`, `:443-444`

**Problem:** STRONG pairs used to skip Gemma (ADR D-4). They now always call `gemma_vision` when previews
exist. Without a TypeSafe key the result is thrown away (`return _strong_plan_pending_review`). A Gemma
failure on such a pair sets `base.error`, and `write_merge_plans` counts every `d.error`
(`apply_merges.py:65`). An outage of a service whose output is unused therefore makes the run exit `2`.

**Recommendation:** Skip the vision call for STRONG pairs when `api_key_from(curate)` is empty, or use the
Gemma verdict in the no-TypeSafe path.

### MIN-4: HITL docs/help now misdescribe STRONG behaviour; config docs incomplete

**Location:** `spark-curate/spark_curate/merge_hitl.py:5`, `spark-curate/spark_curate/__main__.py:102`, `:405`, `spark-curate/README.md` env table

**Problem:** The help text and docstrings still say "hitl_uncertain auto-queues STRONG". After this
change, STRONG can only be approved via TypeSafe *with* previews *and* a vision result. With no key
configured, `hitl_uncertain` silently behaves like `hitl_all`. The `decide_merge.py` module docstring
still cites "STRONG … skip Gemma". The README env table lists only `TYPESAFE_API_KEY`, and
`entrypoint.sh` reads `TYPESAFE_TIMEOUT`, which `docker-compose.yml` doesn't pass through.

**Recommendation:** Update the three help/docstring sites. Print a warning at merge start when
`merge_hitl != hitl_all` and no TypeSafe key is set. Document
`TYPESAFE_MODEL`/`TYPESAFE_BASE_URL`/`TYPESAFE_TIMEOUT`.

---

## Suggestions — Optional

### SUGG-1: Remove dead parameter and duplicated outcome computation in TypeSafe routing

**Location:** `spark-curate/spark_curate/decide_merge.py:135`, `:327`, `:439`

**Suggestion:** `min_merge_confidence` is accepted and then `del`'d (resolve with MAJ-4).
`route_link_score` runs twice, once inside `apply_typesafe_merge_answers` and again in `_record_typesafe`
(`:327`). Returning the outcome from the former removes the second parse. `decided.error = base.error`
(`:439`) is a no-op, because `_strong_plan_pending_review` mutates and returns `base`.

---

## Positive Observations

- ✅ `AdoptImage#sha512` hashes the **original** extracted bytes in 1 MiB chunks, the same algorithm and
  chunking as `ModelFile#calculate_digest`. Digest identity is consistent with the scanner, and memory
  stays flat. The comment at `preview_entry.rb:48-49` explains exactly why.
- ✅ `unique_filename` uses `File.basename` and rejects `.`/`..`, so archive paths can't steer the
  destination outside the model folder.
- ✅ `check_for_problems_job.rb:15` places `ensure_image_preview!` deliberately *before*
  `Problems::NoImage`, so the detector sees the backfilled preview in the same run.
- ✅ spark-curate fails closed throughout. A TypeSafe failure on a STRONG pair is never approved,
  `allow_approve` requires real previews *and* a vision result, and `_weak_overlap_guard` is now applied
  on both the TypeSafe and Qwen paths instead of only one.
- ✅ Extracting `_weak_overlap_guard` into a pure function removed duplicated policy logic and made it
  testable on its own.
- ✅ `typesafe_client` keeps the API key out of logs and exception text, as its docstring promises, and
  uses stdlib HTTP with an explicit timeout.
- ✅ The new Python tests patch both network clients and assert on call counts and the `state` payload
  sent to Jev, not just the final decision.

---

## Testing Recommendations

These are read-derived only. No suite was executed and no coverage percentage is claimed.

- Rails: an archive with ≥2 images and an existing preview, where `model_files.count` stays unchanged.
  This guards CRIT-1.
- Rails: an adoption failure (read-only dest) still writes the thumbnail and marks `preview_ready`
  (MAJ-1).
- Rails: an `EnsurePreview` error inside `CheckForProblemsJob` still runs every later detector (MAJ-3).
- Rails: `HealMissingPreviewsJob` archive-only model, healed once and counted once.
- Python: an autouse `TYPESAFE_API_KEY=""` patch across all merge test modules (MAJ-7).
- Python: the `system_one` HTTP error, non-JSON and missing-`answers` cases, and both `except` fallback
  branches in `decide_merge_pair`.
- Python: a contradictory Jev answer set (score 2, franchise-only 0.95) is not approved (MAJ-4).

---

## Documentation Needs

- README / CLI help: the new STRONG semantics and the TypeSafe dependency of `hitl_uncertain` (MIN-4).
- README env table: `TYPESAFE_MODEL`, `TYPESAFE_BASE_URL`, `TYPESAFE_TIMEOUT`.
- `Archive::AdoptImage` class doc: state when adoption runs (once per model vs per entry) once CRIT-1 is
  resolved.

---

## Next Steps

1. **Before merge:** CRIT-1
2. **Should fix soon:** MAJ-1, MAJ-2, MAJ-3, MAJ-4, MAJ-5, MAJ-6, MAJ-7
3. **Track for later:** MIN-1, MIN-2, MIN-3, MIN-4
4. **Optional:** SUGG-1

---

## Deferred to `sdd-code-security` (noted, not adjudicated)

- spark-curate now sends folder paths, sampled file names and Gemma's preview descriptions to an external
  API (`api.typesafe.ai`, including from `--smoke`). Data egress, API-key handling, and the TypeSafe HTTP
  error body echoed into `MergeDecision.error`/JSONL need a security-lane look.
- `AdoptImage` writes archive-derived filenames into the library tree. The basename sanitization looks
  right from a correctness view; path-safety adjudication belongs to the security lane.

---

## Review Notes

- **Persona dispatch:** `.claude/agents/` does not exist in this repo (`agents_dir_absent`), though a
  regenerable template exists at `sdd-init/assets/personas/code-reviewer.md`. The review ran inline,
  following this skill's procedure and its Phase 3 stack lenses (Python; Ruby/Rails has no persona block,
  so the generic correctness and architecture lenses applied). Run `sdd-init` to bootstrap the persona
  layer.
- **Registry:** `scripts/dev/security_scan_indexer.py` and `sdd/security-reviews/` do not exist in this
  repo. Phase 0 step 3 (scan-id claim), Phase 5 step 7 (dedup) and Phase 7 (registry recording) could not
  run. Under fail-loud-never-block, no `SECSCAN-###`/`SECFIND-###` ids were minted.
- **Coverage gaps (QA gate):** not read: `Problems::NoImage`, `ArchiveEntryService#list!`, the scanner's
  file-discovery path (which may separately re-add adopted files), and spark-curate's
  `candidates.py`/`walk.py`. Phase 6 (remediation plan) is outside `standard` depth. Out of scope:
  `.env.example`/`docker-compose.yml`/`entrypoint.sh` beyond config plumbing, and the untracked `*.log`/
  `*.zip` artifacts in the repo root (which should probably not be committed).
