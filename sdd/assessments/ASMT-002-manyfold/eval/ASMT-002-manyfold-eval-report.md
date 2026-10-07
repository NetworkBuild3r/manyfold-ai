# ASMT-002 eval report

**oracle_ref:** `sdd-assess/assets/eval/assessment-oracle.md`
**oracle_provenance:** `authored_by: human`, `generator_coupled: false`
**Judge:** TypeSafe Jev `jev-1.13.0` (independent of the authoring session; one System One request)

## Metrics

| Signal | Value |
| --- | --- |
| `llm_judge_score` | 0.75 |
| raw score | 2.26 on levels 0–3 (Terrible, Mostly unhelpful, Mostly helpful, Excellent) |
| nearest level | 2 — Mostly helpful (probabilities 0.01 / 0.12 / 0.47 / 0.40, confidence 0.46) |
| normalization | nearest rubric step is 3 of 4, so 3/4 = 0.75 |
| `ac_pass_rate` | 1.00 (7/7 nouls ≥ 0.81) |
| `ragas.faithfulness` | 1.00 (C1–C6 each cite a file read on `origin/main` `d34dc004`) |
| `property_checks` | 16 passed, 0 failed |

## Acceptance nouls

| AC | Noul |
| --- | --- |
| Grounded | 0.81 |
| Both sides read | 0.95 |
| Reuse-first | 0.95 |
| Capability ≠ readiness | 0.98 |
| Falsified | 0.97 |
| BLUF first | 0.89 |
| Precise, harvestable delta named | 0.97 |

Usage: 5284 input tokens, 147 output tokens.

## Verdict

**PASS.** `llm_judge_score` is 0.75, property checks are clean, `ac_pass_rate` is 1.00, faithfulness is 1.00, and the oracle is not generator-coupled.

The score confidence is 0.46 because probability sits between Mostly helpful (0.47) and Excellent (0.40). The nearest level is Mostly helpful, not Excellent. That is the recorded score. It is not rounded up.
