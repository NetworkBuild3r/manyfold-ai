---
spec_id: SPEC-002
title: STRONG pairs go through existing Gemma vision
status: complete
spec_domain: service
initiative: INIT-001-jev-judgments
blocked_by: [SPEC-001]
model: sonnet
prompt: .claude/agents/principal-backend-developer/AGENT.md
security_review: standard
---

# SPEC-002: STRONG pairs go through existing Gemma vision

## Summary

Remove the early return at `decide_merge.py:203`. A STRONG pair uses `clients.gemma_vision` and the existing curator JSON path, the same as a non-STRONG pair that has both previews. Code still owns approval. Do not add a TypeSafe client.

## Dependencies

Blocked by SPEC-001.

## Deliverables

- `spark-curate/spark_curate/decide_merge.py` — delete or stop calling `_strong_merge_decision` as a return that skips vision. STRONG with both previews gets a vision caption, then the existing curator decision. `approved_for_apply` is true only when that decision is merge and both captions exist. Missing preview, vision error, or curator error sets `approved_for_apply` false. Franchise-only refuse at line 199 stays. The weak-overlap guard must not force `keep_separate` on a pair that is STRONG because of archive overlap.
- Tests in `spark-curate/tests/` — any test that expects STRONG to skip Gemma and set confidence 0.85 is rewritten. Cases: both previews and curator says merge → approved; missing preview → not approved; curator failure → not approved; `hitl_all` still does not queue.

No new file named `typesafe_client.py`. No read of `TYPESAFE_API_KEY`.

## Acceptance Criteria

- [ ] `rg -n "_strong_merge_decision" spark-curate/spark_curate/decide_merge.py` shows no call that returns before vision.
- [ ] `rg -n "typesafe|TYPESAFE" spark-curate app` finds nothing.
- [ ] `python -m unittest discover -s tests` in `spark-curate` exits 0.
- [ ] Rails duplicate files have an empty diff.

## Controls & Gates

- **Autonomy level:** edit the curator and its tests. Do not run a merge against a real library. Do not call TypeSafe from product code.
- **Gate actions triggered:** none.
- **Blocking checks:** the unittest command exits 0.
- **Rollback:** revert `decide_merge.py` and the tests. STRONG returns to the 0.85 shortcut.

## Security

- **Sensitivity:** standard. Triggers: untrusted folder names already sent to Gemma; wrong approval merges folders.
- **Security acceptance criteria:**
  - [ ] Missing preview text cannot set `approved_for_apply`.
  - [ ] No new secret is read.
- **Review depth:** standard · **focus areas:** data integrity of merge approval.

## Verification Strategy

- **Claim:** a STRONG pair is not approved unless both previews produced vision text and the existing curator decision is merge.
- **Check + executor:** mechanized — `python -m unittest discover -s tests` in `spark-curate`, including the cases in Deliverables.
- **Pass condition:** the suite exits 0, and the missing-preview STRONG test asserts `approved_for_apply` is false. A test that still expects confidence 0.85 without a vision call fails.

## Open Questions

None.
