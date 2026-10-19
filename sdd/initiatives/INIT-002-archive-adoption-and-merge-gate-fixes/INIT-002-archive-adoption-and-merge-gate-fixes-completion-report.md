# Initiative Completion Report: Archive image adoption hardening + spark-curate merge-gate fixes

**Initiative ID:** INIT-002 (built and merged under the number INIT-001; see initiative doc §14)
**Initiative:** INIT-002-archive-adoption-and-merge-gate-fixes
**Completion Date:** 2026-10-19
**Status:** COMPLETE (deployed; one manual check pending, see Open items)

---

## Executive Summary

Seven specs fixed the one Critical and seven Major findings from the 2026-10-07 code review of the archive
image-preview and spark-curate merge work, and added the owner-requested feature: deleting an adopted image
now removes it from its source archive. Work landed as PR #69 (reconciled with INIT-026 on `main`) and the
security follow-up PR #70, and was deployed on 2026-10-19 through Argo CD (home_k3#32).

---

## Spec Summary

| Spec      | Domain    | Title                                                  | Status   | Change            |
| --------- | --------- | ------------------------------------------------------ | -------- | ----------------- |
| SPEC-001  | data      | Archive-entry to adopted-file provenance + `dismissed` | complete | merged (#69)      |
| SPEC-002  | service   | Safe, idempotent, isolated image adoption              | complete | merged (#69, #70) |
| SPEC-003  | scheduled | Best-effort preview backfill in scan jobs              | complete | merged (#69)      |
| SPEC-004  | service   | Remove adopted images from source archives             | complete | merged (#69, #70) |
| SPEC-005  | frontend  | Delete confirmation for archive-adopted images         | complete | merged (#69)      |
| SPEC-006  | service   | TypeSafe merge approval gate + curator routing         | complete | merged (#69)      |
| SPEC-007  | service   | Hermetic TypeSafe tests + client/fallback coverage     | complete | merged (#69, #70) |
| **Total** |           |                                                        | **7/7**  |                   |

---

## Gates & Controls Summary

| Gate action  | Count | All approved? | Notes |
| ------------ | ----- | ------------- | ----- |
| db_migration | 1     | yes           | additive nullable FK; applied in production before the final deploy; `pg_dump` (108 MB) taken first |
| merge        | 3     | yes           | #69, #70, home_k3#32, each by explicit owner instruction |
| deploy       | 1     | yes           | Argo CD auto-sync from home_k3 after #32; new pod healthy |

SPEC-004's required owner review of the archive-rewrite code was waived by the owner in favour of merging on
green CI; the manual real-zip check is still open.

---

## Security Review

Standard-depth review of the uncommitted changes (`sdd/security-reviews/main-uncommitted/`).

- **Findings:** Critical: 0 · High: 1 · Medium: 3 · Low: 4 · **overall risk at review time:** High
- **Unresolved Critical/High:** **HIGH-1 remains open** (no explicit opt-in or payload minimization for the
  external TypeSafe API). This is a deliberate product decision, not a code defect; no risk acceptance has been
  signed. It is mitigated by TypeSafe being disabled unless an API key is configured, and by the spark-curate
  CronJob being suspended in the cluster.

| Finding | Severity | Class                  | Spec     | Status                |
| ------- | -------- | ---------------------- | -------- | --------------------- |
| HIGH-1  | High     | CWE-201 external send  | SPEC-006 | open (owner decision) |
| MED-1   | Medium   | CWE-59 symlink write   | SPEC-002 | fixed (#70)           |
| MED-2   | Medium   | LLM01 prompt steering  | SPEC-006 | open (owner decision) |
| MED-3   | Medium   | CWE-668 storage bypass | SPEC-002 | fixed (#70)           |
| LOW-1   | Low      | redirect / https       | SPEC-007 | fixed (#70)           |
| LOW-2   | Low      | error text in audit    | SPEC-007 | fixed (#70)           |
| LOW-3   | Low      | key precedence         | SPEC-007 | fixed (#70)           |
| LOW-4   | Low      | SVG adoption           | SPEC-002 | fixed (#70)           |

- **Positive observations:** basename handling already blocked traversal; spark-curate approval paths fail
  closed; the archive rewrite never modifies the original on failure (verified by failure-injection tests).

---

## Test Summary

| Area | Result |
| ---- | ------ |
| New Rails specs | `adopt_image_spec` (16), `remove_entries_spec`, `remove_archive_entries_job_spec` (5), `ensure_preview_spec`, `archive_entry_spec`, plus helper, model and job additions; 416 targeted examples pass (PostgreSQL) |
| Full Rails suite at merge | 2960 examples; failures equal `main`'s pre-existing 120 (ActivityPub, webfinger, search); 2 INIT-026 specs rewritten and passing |
| CI on #69 and #70 | all jobs green (SQLite, MySQL, PostgreSQL, lint, i18n, build) |
| spark-curate | merge tests 73 and TypeSafe tests 32 pass with `TYPESAFE_API_KEY` set and unset; full suite on Linux 343 with 1 mount-layout failure |

---

## Files Changed

| Spec | Key files |
| ---- | --------- |
| SPEC-001 | `db/migrate/20261007120000_add_adopted_model_file_to_archive_entries.rb`, `app/models/archive_entry.rb`, `app/models/model_file.rb` |
| SPEC-002 | `app/services/archive/adopt_image.rb`, `entry_preview.rb`, `preview_entry.rb` |
| SPEC-003 | `app/services/archive/ensure_preview.rb`, `app/jobs/scan/model/heal_missing_previews_job.rb` |
| SPEC-004 | `app/services/archive/remove_entries.rb`, `app/jobs/scan/model_file/remove_archive_entries_job.rb` |
| SPEC-005 | `app/helpers/model_files_helper.rb`, `app/services/archive/delete_confirmation.rb`, file views, `image_carousel.rb` |
| SPEC-006/007 | `spark-curate/spark_curate/decide_merge.py`, `typesafe_client.py`, `apply_merges.py`, tests |

---

## Deviations from the Initiative Plan

- **Numbering:** built as INIT-001, renumbered INIT-002 after merge (id collision with the Jev initiative).
- **INIT-026 reconciliation:** `main` advanced 111 commits and already had an "archive images stay inside the
  archive" design. Per owner decision this initiative's design replaced it; INIT-026's entry-as-preview logic
  was kept only as a fallback (`Archive::EntryPreview`).
- **SPEC-002 ac-4:** the file is renamed into place just before `create!` (Rails needs it on disk), under the same
  model lock, with cleanup on failure.
- **SPEC-003:** archive extraction moved from inline to an enqueued job.
- **SPEC-007:** one production change (API-key redaction in `typesafe_client.py`).
- **Beyond the plan:** PR #70 (security hardening) and home_k3#32 (deploy).
- No git or issue-tracker operations were skipped by the guard.

---

## Challenges & Resolutions

- *Divergence from main:* resolved by building a reconciliation branch off `origin/main` and rewriting the two
  INIT-026 specs that asserted "no copy into the model folder".
- *Environment:* no Ruby on the host; all Rails verification ran in the Docker `test` service. About 90
  pre-existing failures on `main` were isolated by running the baseline in a separate worktree.
- *Deploy:* the digest comment in git was stale; the live pod already ran the #69 build, so the final deploy
  carried only #70 and no migrations.
- *Windows:* line endings and byte-literal escapes needed repair in two files.

---

## Quality Sweep Results

| Check | Result |
| ----- | ------ |
| rubocop on changed Ruby | clean (pre-existing offences remain in untouched `main` code) |
| ruff on changed Python | clean |
| `erb_lint` / `i18n-tasks` | clean |
| Derived-scope tests | PASS (see Test Summary) |

---

## Open items

- **Manual check (SPEC-004):** delete one adopted image from a real zip in production and confirm the archive
  still opens and no longer contains it.
- **HIGH-1 / MED-2:** explicit TypeSafe opt-in and prompt-steering mitigation, pending owner decision.
- **TypeSafe wiring:** Vault key (`shared/common/llm/typesafe`) not yet connected to the spark-curate CronJob.
- **Pre-existing:** about 120 failing Rails specs on `main`; the Docker workflow's smoke-test step.
- **Hygiene:** the pre-deploy database dump sits in the postgres pod's `/tmp` and is lost on restart.

---

## Artifacts

- Initiative: `INIT-002-archive-adoption-and-merge-gate-fixes-initiative.md`
- Spec completion summaries: `specs/completion-summaries/`
- Reviews: `sdd/reviews/main-uncommitted/`, `sdd/security-reviews/main-uncommitted/`
- PRs: manyfold-ai #69, #70; home_k3 #32
