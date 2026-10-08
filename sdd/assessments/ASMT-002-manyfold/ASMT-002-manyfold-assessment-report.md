# ASMT-002 — Manyfold pipeline beyond folder-merge

**Assessment ID:** ASMT-002
**Source:** Manyfold (`origin/main` @ `d34dc004`)
**Assessed:** 2026-09-19
**Recommendation:** Hybrid
**Confidence:** 0.84
**Status:** Complete
**Prior:** ASMT-001 covered the catalog and the STRONG merge shortcut. This assessment does not repeat that unit. On this SHA, `decide_merge.py` no longer contains `_strong_merge_decision` or a `0.85` confidence (`git grep` on `origin/main`).

Harness: Cursor. Guard identities are empty. Discovery snapshot is spark-curate only (61 files, about 19.1 KLOC, Python). Rails citations are `git show` / `git grep` on `origin/main`, not that snapshot.

## Bottom Line Up Front (BLUF)

**Hybrid.** Keep the scan jobs, problem registry, mesh fingerprint, and promote guard as code. Do not spend a second stack on them. The remaining cost is three text judgments that still parse free model JSON: folder organize (`decide.py:272`), category classify (`classify.py:783`), and admission's text curator (`admission.py:547`). Leaving those as unchecked parsers is the risk. Replacing SHA-256 or `Model#merge!` with an agent would drop authority and add a maintenance surface the catalog already has.

## Objectivity & Independent Validation

This report compares the rest of this repo with itself. There is no second platform tree. Bias checks that are in the process: every load-bearing claim cites a file read on `origin/main` (Tier A); a falsification pass tries to kill Hybrid; an independent Jev judge scores the finished report and does not write product code. Platform scores stay blank. `git grep` for `agentic-platform` and `src/shared/common` hits only the ASMT-001 report text, not an implementing package.

## Executive Summary

Value: the library already scans, fingerprints meshes, and applies a reviewed merge plan through `Model#merge!` (`apply_spark_merge_plan_job.rb:142`). Rebuilding that is duplicate spend. Risk: organize still asks Gemma for JSON and will parse the raw vision string if the curator call fails (`decide.py:279`). Classify is stricter: a bad curator response fails closed to `unknown` / `0.0` (`classify.py:785`). That fail-closed behavior is a harvestable delta. Copy it onto organize. Do not copy it by adding a new runtime model inside the Rails process.

Readiness is not the same number as capability. Auth and the problem registry are in place. Tenancy is still absent (ASMT-001, re-checked: no implementing `tenant_id` outside that report). This assessment does not claim the entire pipeline is ready to agentify.

## Assessment

- **Domain summary:** After a file is on disk, Rails scan jobs create models and problems. `spark-curate` also classifies folder names, decides organize moves from a preview, admits intake packs, fingerprints meshes, and refuses to promote onto the live library unless a gate allows it.
- **Tech stack:** Same Rails 8 app as ASMT-001. This slice adds `Problems::Registry` (`registry.rb:4`), `Scan::DedupLibraryJob` (`dedup_library_job.rb:6`), and the Python modules named in the component table.
- **Complexity:** spark-curate discovery, 61 files. CSS and the Rails tree were not in that count on purpose.
- **Modernization opportunities:** Make organize fail closed the way `classify_level` already does. Keep `fingerprint_bytes` on SHA-256 (`mesh_fingerprint.py:301`).
- **Risk areas:** Organize JSON fallback (`decide.py:279`). Admission blocks preview bytes (`admission.py:322`) and then trusts a text curator parse (`admission.py:547`). Promote refuses the live tree unless `allow_live` (`promote.py:167`).

## Persona-Lens Findings

| Lens | Headline finding | Evidence (Tier A) |
| --- | --- | --- |
| Software Architect | Seams already exist. Scan jobs enqueue work. The curator does not own `Model#merge!`. | `dedup_library_job.rb:3`; `apply_spark_merge_plan_job.rb:142` |
| Data Architect | Problem classes register into one lookup. No new table is required for this slice. | `registry.rb:7`; `problems/base.rb:10` |
| Security & Compliance | Promote will not write the live library or `intake/Mega` unless the caller sets the gate. | `promote.py:167`–`184` |
| Platform / Cloud Architect | No agent-package tree. The only `agentic-platform` hit is the previous assessment report. | `git grep` on `origin/main` |
| Day-2 Operations | Dedup scan writes plans and does not apply merges. Apply is a separate job. | `dedup_library_job.rb:3`–`4`; `apply_spark_merge_plan_job.rb:13` |
| Capability-Parity / Reuse | File problem detectors already exist as `detect` methods. Do not rebuild them as prompts. | `empty_file.rb:8`, `missing_file.rb:8`, `non_manifold.rb:8` |
| Agentic / Judgment | Organize, classify, and admission ask a model and parse JSON. Mesh identity is a hash. | `decide.py:263`; `classify.py:782`; `mesh_fingerprint.py:301` |

Conflict: the architect lens says leave the scan jobs alone. The judgment lens says organize still accepts a parsed model string as a category. Hybrid keeps the jobs and tightens the parsers. Averaging those lenses into "agentify the scan" would be wrong.

## Capability & Readiness Scoring Matrix

Platform column is blank. No second tree was scored.

| Dimension | Source | Platform | Notes (Tier-A evidence) |
| --- | --- | --- | --- |
| *Capability* | | | |
| Problem detection beyond duplicates | 4 | — | `Registry.for` (`registry.rb:13`); `detect` on empty, missing, non-manifold |
| Mesh identity | 4 | — | SHA-256 then trimesh identifier (`mesh_fingerprint.py:301`–`302`) |
| Folder organize / category classify | 2 | — | JSON parse of model text (`decide.py:277`, `classify.py:783`) |
| *Readiness / enterprise* | | | |
| AuthN / AuthZ | 4 | — | Unchanged from ASMT-001; this slice does not add a public endpoint |
| Multi-tenancy / isolation | 1 | — | No implementing `tenant_id` on this SHA |
| Durable persistence | 4 | — | Problems stay on the existing table; plans are JSONL the apply job reads |
| Governance / approvals | 3 | — | Dedup does not apply (`dedup_library_job.rb:4`); organize can still act on parsed JSON |
| Deployment / delivery | 4 | — | Curator image is separate from the Rails image (workflow `spark-curate.yml` on this repo) |
| **Capability (avg)** | **3.3** | **—** | Hash identity is not the same as folder naming |
| **Readiness (avg)** | **3.2** | **—** | Tenancy is the low score; it is not a reason to rewrite `detect` |

## Technical Component Analysis

| Source unit | LOC | Nature | Target home | Platform support | Status | Rationale |
| --- | --- | --- | --- | --- | --- | --- |
| `Problems::Registry` and `detect` methods | n/a | Deterministic | Backend service | In this app | Provided (use as-is) | Lookup plus `detect` (`registry.rb:13`, `base.rb:10`) |
| `Scan::DedupLibraryJob` | n/a | Deterministic | Backend service | In this app | Provided (use as-is) | Evaluation-only (`dedup_library_job.rb:3`) |
| `Scan::ApplySparkMergePlanJob` | n/a | Deterministic | Backend service | `Model#merge!` | Provided (use as-is) | One apply path (`apply_spark_merge_plan_job.rb:142`) |
| `mesh_fingerprint.fingerprint_bytes` | n/a | Deterministic | Backend service | None beyond this module | Provided (use as-is) | SHA-256 (`mesh_fingerprint.py:301`) |
| `promote.assert_not_live_tree` | n/a | Deterministic | Backend service | None | Provided (use as-is) | Refuses live paths (`promote.py:167`) |
| `decide.decide_one` | n/a | Judgment | Keep the batch job; code owns the failure | Gemma already called | Adapt | Parses JSON (`decide.py:277`); fallback parses raw vision (`decide.py:280`) |
| `classify.classify_level` | n/a | Judgment | Keep the batch job; code owns the failure | Curator chat already called | Adapt | Fail-closed to unknown (`classify.py:785`) |
| `admission` text curator | n/a | Judgment | Keep admission; do not open images here | Preview blocked in code | Adapt | `_never_preview` (`admission.py:322`); parse at `547` |

## Recommendation

Hybrid, confidence 0.84.

### Options Key

- **Hybrid — Choose.** Deterministic scan, hash, promote, and problem `detect` stay. Organize and classify stay in the curator, but a parse failure must skip, the way classify already does.
- **Refactor — Reject.** Replacing the JSON parse with a stricter constant still leaves `classify_level` asking a model what a folder is (`classify.py:777`).
- **Agentify — Reject.** `fingerprint_bytes` and `target.merge!` are same-input outcomes (`mesh_fingerprint.py:301`, `apply_spark_merge_plan_job.rb:142`).
- **No action — Reject.** Organize still parses model text into a category (`decide.py:287`). That gap is not closed by the problem registry.

**Why:** capability 3.3 is pulled down by organize/classify at 2. Readiness 3.2 is a different axis. Confidence stops at 0.84 because the platform column is blank and because ASMT-001 already took the merge seam; this score is only for the units in the table above.

## Evidence & Falsification

| # | Claim | Type | Tier | Source(s) cited | Verification method | Load-bearing? | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C1 | Organize parses curator JSON and falls back to raw vision | nature | A | `decide.py:272`, `:280` | `git show origin/main` | yes | verified |
| C2 | Classify fails closed on curator error | nature | A | `classify.py:783`–`791` | `git show origin/main` | yes | verified |
| C3 | Mesh identity is SHA-256 of member bytes | nature | A | `mesh_fingerprint.py:301` | `git show origin/main` | yes | verified |
| C4 | Dedup job does not apply merges; apply is `Model#merge!` | capability | A | `dedup_library_job.rb:4`, `apply_spark_merge_plan_job.rb:142` | `git show origin/main` | yes | verified |
| C5 | Admission does not open preview bytes | nature | A | `admission.py:322`, `:339` | `git grep origin/main` | yes | verified |
| C6 | No agent package implementation on this SHA | parity | A | `git grep agentic-platform` matches only ASMT-001's report | `git grep` | yes | verified |

**Hypothesis:** Hybrid is right for this slice: keep scan and hash, adapt the three JSON judgments, do not agentify merge apply.

| # | How it could be wrong | Tested against (Tier-A evidence) | Survived? |
| --- | --- | --- | --- |
| F1 | Organize is already deterministic, so No action | `decide_one` sends `VISION_PROMPT` and `extract_json_object` (`decide.py:254`, `:277`). | no |
| F2 | The scan jobs should become an agent | `DedupLibraryJob` documents evaluation-only (`dedup_library_job.rb:3`). Apply is `merge!` (`apply_spark_merge_plan_job.rb:142`). | no |
| F3 | Classify is unsafe because it parses JSON, so Agentify the whole curator | On curator failure it returns `unknown` and `0.0` (`classify.py:791`), which is a code gate, not a prompt. | no |

**Result:** no falsifier survived. Recommendation holds at 0.84. Independent Jev judge (`jev-1.13.0`) nearest level is Mostly helpful (raw score 2.26 of 0–3; probability 0.47 on that level, 0.40 on Excellent). `llm_judge_score` 0.75. Property checks 16/16. Verdict **PASS**. Details in `eval/ASMT-002-manyfold-eval-report.md`.

## Risks

- Treating ASMT-001's `0.85` citation as still true on `d34dc004`. It is not. `git grep` found no `_strong_merge_decision` on this SHA.
- An organize fallback that accepts raw vision JSON (`decide.py:280`) can still set a category when the curator is down.
- Promoting with `allow_live` bypasses `assert_not_live_tree` (`promote.py:169`). That gate is intentional and must stay in code.

## Spec Skeleton

### Phase 1: Foundation

- SPEC-001 · Service — organize parse failure sets `action=skip` and does not read the raw vision string (`decide.py:279`). Match classify's fail-closed behavior (2–3 h).

### Phase 2: Backend Core

- SPEC-002 · Service — golden tests that `fingerprint_bytes` is SHA-256 plus trimesh, and that a truncated buffer never reaches it (`mesh_fingerprint.py:295`) (2–3 h).
- SPEC-003 · Service — `Scan::ApplySparkMergePlanJob` remains the only caller of `Model#merge!` from a curator plan (`apply_spark_merge_plan_job.rb:142`) (2 h).

### Phase 3: Judgment boundaries

- SPEC-004 · Service — `classify_level` stays fail-closed (`classify.py:785`). Do not add a second category store (2 h).
- SPEC-005 · Service — admission keeps `_never_preview` (`admission.py:322`). A curator failure stays `curator_failed`, not a silent attach (2–3 h).

### Phase 4: Frontend

- SPEC-006 · Frontend — no new problems UI. `Problems::Registry` stays the lookup (`registry.rb:13`) (1 h).

### Phase 5: Deploy

- SPEC-007 · Infrastructure — curator image only. Do not rebuild the Rails image for this slice (2 h).

## Next Step

`create-initiative` can turn this skeleton into specs with `source` `ASMT-002`. This assessment does not create that initiative. It does not put a TypeSafe client in the product. Jev scores the report only.
