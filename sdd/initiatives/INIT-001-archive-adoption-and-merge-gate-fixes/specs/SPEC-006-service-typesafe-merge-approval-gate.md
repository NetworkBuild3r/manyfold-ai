# SPEC-006 · Service: TypeSafe merge approval gate + curator routing

## Metadata

```yaml
spec_id: SPEC-006
initiative_id: INIT-001
title: Require confidence and consistent answers for TypeSafe merge approval; route curator outcomes to human review
domain: service
status: complete
primary_prompt: .claude/agents/principal-backend-developer/AGENT.md   # agents dir absent — described persona (disclosed)
supplement_prompts: []
model: sonnet
autonomy_level: auto_tests
gate_actions: []
reversibility_class: branch
security_review: standard
estimated_effort: 3 hours
blocked_by: None
blocks: [SPEC-007]
```

---

## Description

**Context:**
- MAJ-4: `apply_typesafe_merge_answers` approves on the rounded score alone. It drops
  `min_merge_confidence` and ignores Jev's `same_printable_product` / `character_or_franchise_only`
  answers.
- MAJ-5: the "a human should decide" (curator) outcome becomes `keep_separate`, so it is filed as REFUSE
  and never reaches the `MERGE?` review log.

**Owner decisions (2026-10-07):**
- Approval requires confidence ≥ `min_merge_confidence` *and* consistent answers.
- A curator outcome becomes an unapproved merge plan.

**Scope (in):** `spark-curate/spark_curate/decide_merge.py` (`apply_typesafe_merge_answers`,
`_record_typesafe`, the failure branch), `apply_merges.py` / `__main__.py` summary counts, README wording,
and tests in `tests/test_typesafe_merge.py`.

**Scope (out):** Client/HTTP tests and hermeticity (SPEC-007); MIN-3/MIN-4.

## Acceptance Criteria

- [x] ac-1 (MAJ-4): A merge is approved only when **all** of the following hold:
  - the routed outcome is `merge`;
  - `link_state.confidence ≥ curate.min_merge_confidence`;
  - `same_printable_product.noul ≥ 0.5`;
  - `character_or_franchise_only.noul < 0.5`.

  — covered: yes
- [x] ac-2 (MAJ-4): A `merge` outcome that fails any of those conditions returns `decision="merge"`,
  `approved=False`. Its reason is tagged with the failing condition, e.g. `(low confidence)` or
  `(contradicts: franchise_only)`. — covered: yes
- [x] ac-3 (MAJ-5): The curator outcome returns `decision="merge"`, `approved=False`, reason `… (curator)`.
  For non-STRONG signals, `classify_hitl_band` yields `UNCERTAIN`; it appears as a `MERGE?` line in the run
  log; and it is never auto-queued under any `MERGE_HITL` mode. — covered: yes
- [x] ac-4: `merge-summary-*.json` adds a `typesafe_curator` count, and `merge_suggested` includes curator
  plans. — covered: yes
- [x] ac-5 (SUGG-1): The `min_merge_confidence` parameter is actually used; the outcome is computed once
  and returned; the no-op `decided.error = base.error` is removed. — covered: yes
- [x] ac-6: The README "Same character ≠ same model" paragraph states the new approval rule. — covered: yes
- [x] ac-7: The existing tests in `tests/test_typesafe_merge.py`, `test_decide_merge.py`,
  `test_merge_candidates.py` and `test_merge_hitl.py` still pass, updated only where they asserted the old
  approval rule. — covered: yes

## Assumptions Ledger

| id    | item | interpretation | tone | resolved |
| ----- | ---- | -------------- | ---- | -------- |
| aud-1 | Gate on confidence + consistency | Yes (owner, 2026-10-07) | clear | yes |
| aud-2 | Curator → unapproved merge plan | Yes (owner, 2026-10-07) | clear | yes |
| aud-3 | NOUL thresholds | 0.5 for both, as module constants (not config) | clear (owner, 2026-10-07) | yes |
| aud-4 | Missing NOUL answer (key absent) | Treated as failing consistency, so not approved | clear (owner, 2026-10-07) | yes |

## Deliverables

- [x] `spark-curate/spark_curate/decide_merge.py`
- [x] `spark-curate/spark_curate/apply_merges.py` and/or `__main__.py` (summary count)
- [x] `spark-curate/README.md`
- [x] Tests: `spark-curate/tests/test_typesafe_merge.py`, plus `test_merge_hitl.py` for band and log of a
  curator plan

## Technical Requirements

- [x] Type hints on all changed functions. Keep the stdlib-only dependency footprint.

## Security

- **Sensitivity:** standard. Triggers: an external-service decision gating a destructive merge.
- **Security acceptance criteria:**
  - [x] Every new branch fails closed: any unparsable or missing answer means not approved.

## Verification Strategy

- **Claim:** TypeSafe approval follows ac-1 exactly, and curator outcomes reach the human review surface
  without ever being auto-queued.
- **Check + executor:** mechanized: `cd spark-curate && python -m unittest discover -s tests -v`.
- **Pass condition:** There is a parametrized table test with one row per failing condition, each
  asserting `approved=False`, plus one row with all conditions passing that asserts `approved=True`. A
  curator plan asserts band `UNCERTAIN` and `should_auto_apply(...) is False` for all three modes. The full
  suite is green.

## Integration Points

- SPEC-007 adds client and fallback coverage on top of these semantics.
- **Provenance tag:** `INIT-001/SPEC-006`
