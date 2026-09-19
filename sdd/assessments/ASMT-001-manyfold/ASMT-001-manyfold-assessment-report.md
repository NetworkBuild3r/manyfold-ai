# Codebase Assessment: Manyfold

**Assessment ID:** ASMT-001  ·  **Status:** Complete
**Source:** `git@github.com:NetworkBuild3r/manyfold-ai.git` `origin/main` @ `8445b75a652a46ff4320626aab764e91c7058adb`
**Assessed:** 2026-09-19  ·  **Analyst:** Cursor session (`harness_source=cursor`)
**Recommendation:** Hybrid  ·  **Confidence:** 0.86
**Pipeline mode:** brownfield

Working tree note: local `main` was `7e991274` (64 commits behind `origin/main`) with uncommitted `spark-curate` edits. Those edits are not cited as the source. A scoped search of `origin/main` for `agentic-platform` and `src/shared/common` returned no matches, so this report does not claim an external platform already hosts Manyfold.

## Bottom Line Up Front (BLUF)

**Recommendation: Hybrid.** Keep the Rails catalog, scan jobs, and problem resolution as the authoritative service, and move folder-level "same printable product" judgment out of the curator script into an agent that cannot approve a merge by itself. That split avoids a second catalog stack and stops a file-overlap heuristic from merging two different models when apply policy is loosened. The maintenance surface stays one Rails app plus one small judgment package, not a rewrite of the library.

## Objectivity & Independent Validation

This report compares Manyfold to an agent-platform layout that is not checked out here. Bias mitigations:

- **Evidence discipline:** load-bearing claims cite `origin/main` files read in this session, or a scoped `git grep` that returned no matches. The dirty working tree is not used as proof.
- **Falsification pass:** the Hybrid headline was tested against three contrary readings. None survived. See Evidence & Falsification.
- **Independent judge:** TypeSafe Jev (`jev-latest`) scored this report against the human-authored oracle after the report was written. The authoring session did not assign the rating. See `eval/`.

## Executive Summary

**We recommend one of the following paths:**

1. **Hybrid** — keep the Rails catalog; agentify only folder-merge judgment.
2. **Refactor** — leave merge decisions in Python with stricter thresholds and no agent package.
3. **Agentify** — replace the catalog UI and scan pipeline with an agent.
4. **No action** — treat the current curator as already sufficient.

**Based on these findings, the recommendation is Hybrid.**

- **Where the source is today:** a self-hosted Rails 8 library (`Gemfile:7`) with Devise and Pundit (`Gemfile:87`, `Gemfile:105`), a `problems` table (`db/schema.rb:560`), and a separate Python curator that plans folder merges.
- **What it is missing that an agent platform would add:** no agent-package tree exists in this repo, so folder "same product" decisions still run inside `spark-curate` and a STRONG structural pair is approved without a preview comparison.
- **Capability parity:** file-duplicate detection in Rails is a different capability from folder-merge judgment. Matching digests does not mean the folder curator is production-ready to auto-apply.
- **Harvestable deltas:** `Problem.resolve_batch` is a single resolution entry (`app/models/problem.rb:152`). `MergeHistory` already records merges (`app/models/merge_history.rb:1`). `ModelFile#duplicate?` refuses non-geometry files unless the file is an archive (`app/models/model_file.rb:237`). A local, uncommitted Jev review path exists on the behind checkout and is not part of `8445b75`.

## Assessment

- **Domain summary:** Manyfold stores a 3D-model library, scans the filesystem into the database, and flags problems on model files. `spark-curate` is a separate batch process that proposes folder moves and merges. It does not replace the Rails app.
- **Tech stack:** Ruby on Rails 8.0 (`Gemfile:7`), PostgreSQL (`Gemfile` gem `pg`), Sidekiq (`Gemfile:124`), Hotwire (Stimulus and Turbo in `package.json` dependencies from the discovery snapshot), Docker images under `docker/` including `docker/manyfold.dockerfile`. Curator: Python under `spark-curate/`.
- **Complexity:** discovery of the dirty working tree counted about 49,455 Ruby lines and 6,561 Python lines. CSS and log files dominated that snapshot and are not treated as application size. Assessed behavior is taken from `origin/main`, not from that snapshot's line counts.
- **Modernization opportunities:**
  - Split STRONG folder-merge approval out of `_strong_merge_decision` so structural overlap is evidence, not permission.
  - Keep `Problems::Duplicate.detect` on digest equality for files.
- **Risk areas:**
  - STRONG pairs set confidence `0.85` and skip vision (`spark-curate/spark_curate/decide_merge.py:164` and the return at line 205).
  - `hitl_off` can queue uncertain approved merges (`spark-curate/spark_curate/merge_hitl.py:6`). Default remains `hitl_all` (line 4).
  - No `tenant_id` or `row_level` match under `origin/main` `db/schema.rb` or `app/models`.

## Persona-Lens Findings

| Lens | Headline finding | Evidence (Tier A — cite files) |
| --- | --- | --- |
| Software Architect | Brownfield seams are already separate: Rails catalog versus `spark-curate`. Do not rewrite the catalog to extract the curator. | `Gemfile:7`; `spark-curate/spark_curate/decide_merge.py:178` |
| Data Architect | Problems and merge history are durable records. No tenant column was found. | `db/schema.rb:560`; `app/models/merge_history.rb:1`; scoped search, no `tenant_id` |
| Security & Compliance | Request authorization exists. Curator approval is a process flag, not Pundit. STRONG can be approved without a person when apply mode allows it. | `Gemfile:87`; `Gemfile:105`; `app/policies/problem_policy.rb:1`; `decide_merge.py:164` |
| Platform / Cloud Architect | The app already ships container files. There is no agent-package deploy tree in this repo. | `docker/manyfold.dockerfile`; search for `agentic-platform` returned no matches |
| Day-2 Operations | Merge undo state exists as a model. Curator apply is gated by `MERGE_HITL`, default plans only. | `app/models/merge_history.rb:1`; `merge_hitl.py:4` |
| Capability-Parity / Reuse | This repo does not already provide an agent package for folder identity. File-duplicate detection is provided inside Rails and should be reused, not rebuilt. | `app/models/problems/duplicate.rb:8`; no `src/shared/common` matches |
| Agentic / Judgment | File `duplicate?` is deterministic. Folder STRONG merge is a heuristic that assigns a fixed confidence and skips preview comparison. | `app/models/model_file.rb:237`; `decide_merge.py:164`–`205` |

Conflict, not averaged: the architect lens says keep Rails. The judgment lens says do not leave STRONG approval in the batch script. Hybrid is the resolution. The parity lens vetoes No action because the agent side was not found.

## Capability & Readiness Scoring Matrix

Platform column is blank on purpose. No second tree was available to score.

| Dimension | Source | Platform | Notes (Tier-A evidence) |
| --- | --- | --- | --- |
| *Capability* | | | |
| Library catalog and problem workflow | 4 | — | Rails 8 app, `problems` table, `resolve_batch` (`problem.rb:152`) |
| File duplicate detection | 4 | — | `duplicate?` requires geometry or archive (`model_file.rb:237`) |
| Folder same-product judgment | 2 | — | STRONG sets `0.85` and skips Gemma (`decide_merge.py:164`) |
| *Readiness / enterprise* | | | |
| AuthN / AuthZ | 4 | — | Devise (`Gemfile:87`), Pundit (`Gemfile:105`), `ProblemPolicy` |
| Multi-tenancy / isolation | 1 | — | No `tenant_id` / `row_level` match in schema or models |
| Durable persistence | 4 | — | `problems` table; `MergeHistory` |
| Governance / approvals | 3 | — | Default `hitl_all` plans only (`merge_hitl.py:4`); STRONG still self-approves |
| Deployment / delivery | 4 | — | `docker/manyfold.dockerfile` and sibling Dockerfiles |
| **Capability (avg)** | **3.3** | **—** | File detection is not folder-merge readiness |
| **Readiness (avg)** | **3.2** | **—** | Tenancy is the low score; auth is not the gap |

## Technical Component Analysis

| Source unit | LOC | Nature | Target home | Platform support | Status | Rationale (cite behavior) |
| --- | --- | --- | --- | --- | --- | --- |
| `app/models/model_file.rb` `duplicate?` | n/a | Deterministic | Backend service | None in-repo beyond this app | Provided (use as-is) | Same digest, size, and geometry-or-archive gate (`model_file.rb:230`–`239`) |
| `Problems::Duplicate` | n/a | Deterministic | Backend service | `Problem.create_or_clear` | Provided (use as-is) | `detect` only creates or clears (`duplicate.rb:8`–`9`); resolve goes through `resolve_batch` |
| `spark-curate` candidate pairing | n/a | Deterministic | Backend service | No shared service tree | Adapt | Pairing rules stay in code; not re-expressed as a prompt |
| `decide_merge._strong_merge_decision` | n/a | Judgment | Agent package | No agent package on `origin/main` | Build | Fixed confidence `0.85`, skip Gemma (`decide_merge.py:164`–`174`, return at `205`) |
| `merge_hitl.py` | n/a | Orchestration | Agent orchestrator + API | HITL modes already coded | Adapt | `hitl_all` / `hitl_uncertain` / `hitl_off` (`merge_hitl.py:4`–`6`) stay as policy code |
| Rails UI (`config/routes.rb` problems) | n/a | Presentation | Frontend app | Existing Hotwire UI | Provided (use as-is) | `resources :problems` (`config/routes.rb:227`) |
| `Gemfile` secrets and endpoints | n/a | Config | Infra (secrets) | Vault is outside this repo | Adapt | Do not copy API keys into the agent package |
| `db/schema.rb` `problems` | n/a | Persistence | Data layer | Table exists; no RLS found | Adapt | `create_table "problems"` (`db/schema.rb:560`); add tenant scope only if a platform requires it |

## Recommendation

Hybrid, confidence 0.86.

### Options Key

- **Hybrid — Choose.** Deterministic catalog stays. Folder identity judgment is built as an agent with no self-approval.
- **Refactor — Reject.** Tightening the `0.85` constant still leaves a semantic decision inside a batch script (`decide_merge.py:164`).
- **Agentify — Reject.** Scan, digest, and `resolve_batch` are same-input outcomes (`problem.rb:152`). Replacing them with an agent drops authority.
- **No action — Reject.** Reuse-first search found file-duplicate detection and did not find an agent package. The curator gap is real.

**Why:** capability average 3.3 is pulled down by folder judgment at 2, while file detection is 4. Readiness average 3.2 is not the same conclusion as that capability split. Confidence is not 0.90 because the external platform tree was absent, so platform scores are intentionally blank.

## Evidence & Falsification

| # | Claim | Type | Tier | Source(s) cited | Verification method | Load-bearing? | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C1 | Catalog is Rails 8 with Devise and Pundit | capability | A | `Gemfile:7`, `Gemfile:87`, `Gemfile:105` | `git grep` on `origin/main` | yes | verified |
| C2 | File duplicates are digest plus geometry-or-archive | nature | A | `model_file.rb:237`, `duplicate.rb:8` | `git show` / `git grep` | yes | verified |
| C3 | STRONG merge skips preview comparison and sets 0.85 | nature | A | `decide_merge.py:164`, `:205` | `git grep` on `origin/main` | yes | verified |
| C4 | No agent-package home in this repo | parity | A | search `agentic-platform`, `src/shared/common` | `git grep -l` on `origin/main`, no matches | yes | verified |
| C5 | No tenant column found | readiness | A | `db/schema.rb`, `app/models` | `git grep` `tenant_id` / `row_level`, no matches | yes | verified |
| C6 | Default curator mode does not queue merges | readiness | A | `merge_hitl.py:4` | file read via `git show` | no | verified |

**Hypothesis:** Hybrid is the right landing: keep Rails, agentify folder-merge judgment.

| # | How it could be wrong | Tested against (Tier-A evidence) | Survived? |
| --- | --- | --- | --- |
| F1 | STRONG merge is already deterministic, so Refactor is enough | `_strong_merge_decision` writes a constant `0.85` and skips Gemma (`decide_merge.py:164`). That is not an equality check like `duplicate?`. | no |
| F2 | The whole app should be an agent | `resolve_batch` and `Duplicate.detect` are explicit code paths (`problem.rb:152`, `duplicate.rb:8`). | no |
| F3 | No action, because Manyfold already is the platform | File detection exists (`duplicate.rb`). An agent package does not (`git grep` empty). Those are different units. | no |

**Result:** no falsifier survived. Recommendation holds at 0.86. Independent Jev judge (`jev-1.13.0`) nearest rubric level is Excellent (raw score 2.51 of 0–3; 0.62 on that level). Property checks 16/16. Verdict: **PASS**. Details in `eval/ASMT-001-manyfold-eval-report.md`.

## Risks

- Applying `hitl_uncertain` or `hitl_off` on current `origin/main` can queue a STRONG merge that never saw a preview (`decide_merge.py:205`, `merge_hitl.py:5`).
- Assessing the dirty checkout instead of `8445b75` would describe uncommitted Jev code that is not on the remote tip.
- Adding RLS later is a data migration, not a reason to rewrite problem detection.

## Spec Skeleton

### Phase 1: Foundation

- SPEC-001 · Infrastructure — curator runtime secrets stay in the existing secret store; no key in the agent package (2–4 h).

### Phase 2: Backend Core

- SPEC-002 · Service Layer — keep `ModelFile#duplicate?` and `Problems::Duplicate` as the file-level contract; golden tests on geometry versus archive (2–4 h).
- SPEC-003 · API Layer — folder-merge agent may only enqueue through the existing merge apply path; it does not gain a second resolve API (2–4 h).

### Phase 3: Agentic

- SPEC-004 · Agent Package — folder identity judgment. Inputs are pair state (names, signals, preview text). Output is keep / curator / merge. Code withholds approval when preview text is absent (4–6 h).
- SPEC-005 · Agent Package — orchestrator calls SPEC-004 only after structural pairing; `MERGE_HITL` remains the apply gate (3–5 h).

### Phase 4: Frontend

- SPEC-006 · Frontend — no new problems UI. Operators keep `resources :problems` (`config/routes.rb:227`) (2 h).

### Phase 5: Deploy

- SPEC-007 · Infrastructure — run the judgment package beside the existing `docker/manyfold.dockerfile` image; smoke one dry-run merge plan (3–5 h).

## Next Step

Proceed to create the initiative? SDD `create-initiative` can turn SPEC-001–SPEC-007 into one Hybrid initiative with `source` `ASMT-001`. This assessment does not create that initiative.
