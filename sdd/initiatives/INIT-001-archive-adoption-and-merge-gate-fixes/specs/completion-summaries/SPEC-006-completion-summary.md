# SPEC-006 Completion Summary — TypeSafe merge approval gate + curator routing

**Provenance:** `INIT-001/SPEC-006` · **Completed:** 2026-10-07 · **Findings closed:** MAJ-4, MAJ-5, SUGG-1

## Changes
- `spark_curate/decide_merge.py`: `apply_typesafe_merge_answers` now returns
  `(decision, confidence, target, reason, approved, outcome)`. A merge is approved only when the score
  rounds to merge, `link_state.confidence >= min_merge_confidence`, `same_printable_product.noul >= 0.5`,
  and `character_or_franchise_only.noul < 0.5`. A missing or unparsable answer fails closed. A merge that
  fails a check stays `decision="merge"` and unapproved, with the failing check tagged in its reason. The
  curator outcome becomes an unapproved merge plan (`(curator)`). `_record_typesafe` uses the returned
  outcome instead of recomputing it, and the no-op `decided.error = base.error` was removed.
- `spark_curate/apply_merges.py`: `write_merge_plans` result adds a `typesafe_curator` count.
- `README.md`: states the approval rule.
- `tests/test_typesafe_merge.py`: approval table (7 failing conditions), unparsable NOUL, curator plan,
  keep-separate, curator band/HITL matrix, curator review-log line and count.

## Verification
- `env -u TYPESAFE_API_KEY python -m unittest discover -s tests`: 63 tests, OK.
- `ruff check spark_curate tests`: 2 errors, both pre-existing in untouched files
  (`__main__.py:294`, `decide.py:3`).

## Owner decisions applied
- NOUL cut-offs are 0.5 constants in code. A missing answer is not approved (2026-10-07).
