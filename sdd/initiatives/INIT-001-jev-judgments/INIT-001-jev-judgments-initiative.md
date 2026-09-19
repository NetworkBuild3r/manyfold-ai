# INIT-001: Vision on STRONG merges, Jev only while coding

**Status:** in_progress
**Created:** 2026-09-19
**Amended:** 2026-09-19 — Jev does not ship in Manyfold or spark-curate.
**Branch:** `jev-judgments` — worktree at `.claude/worktrees/jev-judgments` from `origin/main` `8445b75a652a46ff4320626aab764e91c7058adb`.
**Discipline Profile:** `software`. `network` is also active and was not chosen.
**Source:** ASMT-001. User constraint: Jev is for vibe-coding this initiative, not for Manyfold itself.

## 1. Goal

On `origin/main`, a STRONG merge pair skips Gemma and returns confidence 0.85 (`spark-curate/spark_curate/decide_merge.py:203` calls `_strong_merge_decision` at line 164). That path must use the existing vision call and the existing code gates. TypeSafe is not a runtime dependency.

Jev (`jev-latest`) is the coding judge for this initiative: spec amendments, acceptance checks, and review questions the orchestrator asks. It is not imported by Rails or by spark-curate.

## 2. Why

ASMT-001 (Hybrid, 0.86) said keep the Rails catalog and stop treating STRONG as permission. The first draft of this initiative put a TypeSafe client in the curator. The user rejected that. A Jev placement question came back `curator_only` at probability 0.65 with confidence 0.48, and the "vibe coding means agent-only" noul was 0.50. Code does not act on a split that wide when the user was explicit. The follow-on choice `strong_needs_vision` was 0.99 and is the product scope.

## 3. Domain analysis

| Domain | In scope | Why |
| --- | --- | --- |
| docs | Yes | The no-runtime-Jev rule has to be written before the code change, or the next spec will grow a client. |
| infrastructure | No | No new secret. `TYPESAFE_API_KEY` stays in the agent environment, not the app. |
| data | No | No schema change. |
| service | Yes | One function in `decide_merge.py`. |
| api | No | No new endpoint. `Problem.resolve_batch` stays the only resolve path. |
| event | No | |
| scheduled | No | |
| frontend | No | Problems UI unchanged. |

## 4. Specs

| Spec | Domain | Status | Title | Depends on | Effort |
| --- | --- | --- | --- | --- | --- |
| SPEC-001 | docs | complete | No runtime Jev; STRONG is not permission | — | 2h |
| SPEC-002 | service | complete | STRONG pairs go through existing Gemma vision | SPEC-001 | 4h |

SPEC-003 and SPEC-004 from the first draft are withdrawn. They would have shipped a TypeSafe client.

## 5. Timeline

| | |
| --- | --- |
| Critical path | SPEC-001 → SPEC-002 = 6 hours |
| Realistic duration | 6 × 1.3 = 8 hours |
| Calendar estimate | 2 days |

## 6. Controls & Gates

- **Default autonomy:** branch-only. No merge apply against a real library. No Vault calls.
- **One-way actions expected:** none.
- **Approval owner:** Brian Nelson before any `hitl_off` run.

## 7. Agent Behavior Overrides

Omitted.

## 8. Threat Model

- **Attack surface:** unchanged. Gemma is already called from the curator. This initiative adds that call on the STRONG path.
- **Trust boundaries:** folder names and preview bytes stay inside the existing curator process.
- **Data classification:** no new secret in the product.
- **STRIDE-lite:** a model caption must not set `approved_for_apply` when a preview is missing.
- **Security-sensitive specs:** none at `required`. SPEC-002 is `standard` (data integrity of merge approval).

## 9. Risk Assessment

| Risk | Probability | Impact | Mitigation |
| --- | --- | --- | --- |
| A later spec adds `typesafe_client.py` anyway | M | H | SPEC-001 is a blocker. SPEC-002's AC forbids that file. |
| STRONG archive-overlap pairs get forced keep_separate by the weak-overlap guard | M | M | SPEC-002 says that guard does not apply to STRONG. |
| Jev's low-confidence `curator_only` answer gets treated as permission later | L | H | Recorded here. Revisit only if the user explicitly allows a runtime client. |

## 10. Success Criteria

- [ ] No `typesafe` import or `TYPESAFE_API_KEY` read under `spark-curate/` or `app/` on this branch.
- [ ] STRONG no longer returns at `decide_merge.py:205` before vision.
- [ ] `MERGE_HITL=hitl_all` still queues nothing.
- [ ] `ModelFile#duplicate?` and `Problems::Duplicate` are unchanged.

## 11. Next Steps

1. Enter the existing worktree (orchestration Outcome C).
2. Execute SPEC-001, then SPEC-002.
3. Jev is asked at each acceptance judgment. It is not called from product code.

## Assumptions ledger

| ID | Text | Status | Interpretation |
| --- | --- | --- | --- |
| A1 | "Everywhere" meant every product LLM seam. | resolved, superseded | User override 2026-09-19: Jev is for vibe coding, not Manyfold. |
| A2 | Dirty local `main` is not the baseline. | resolved | Charter is `origin/main` `8445b75`. |
| A3 | Jev `curator_only` (0.65, confidence 0.48) does not override the user. | resolved | Agent-only. Product change is `strong_needs_vision` (0.99). |

## Reflection (amended)

| Dimension | Score |
| --- | --- |
| Completeness | 8 |
| Accuracy | 9 |
| Clarity | 9 |
| Feasibility | 8 |
| Guardrails | 8 |

Confidence = 42/50 = 0.84. Each dimension ≥ 6.

## Orchestration note

Worktree engagement is Outcome C: branch `jev-judgments` is checked out at `.claude/worktrees/jev-judgments`, not in the session toplevel `c:\Users\BrianNelson\Projects\mfold`. Declining to enter does not make an in-place checkout safe: git will refuse to check out `jev-judgments` in the toplevel while the worktree holds it.
