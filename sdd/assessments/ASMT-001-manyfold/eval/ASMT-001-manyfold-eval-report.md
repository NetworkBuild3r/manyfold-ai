# Assessment Evaluation Report — ASMT-001

- **Target:** `sdd/assessments/ASMT-001-manyfold/ASMT-001-manyfold-assessment-report.md`
- **Oracle:** `assets/eval/assessment-oracle.md@1.2`
- **Oracle provenance:** authored_by: human · generator_coupled: false
- **Judge:** TypeSafe Jev `jev-1.13.0` (independent of the authoring session; no Task sub-agent) · temperature n/a (System One)
- **Evaluated at:** 2026-09-19T20:50:00Z
- **Verdict:** PASS

Jev replaced the Phase 8 fresh sub-agent. `harness_source` for this session is `cursor`. The judge received the report, the oracle, and the grounding excerpts. It did not receive the authoring prompt.

## Metrics

| Signal | Score | Notes |
| --- | ---: | --- |
| `llm_judge_score` (1–4 → [0,1]) | 1.00 | Nearest level index 3 → rating 4. Raw score 2.51 (probabilities 0.05 / 0.02 / 0.31 / 0.62). `(4-1)/3 = 1.00`. |
| `ragas.faithfulness` | 1.00 | Load-bearing claims C1–C5 each cite an `origin/main` path checked with `git grep` or `git show`. |
| `ragas.answer_relevance` | 0.79 | Jev `ac_exec` noul. The report answers Refactor / Agentify / Hybrid / No action. |
| `ragas.context_precision` | 0.92 | Jev `ac_precise` noul. Cited excerpts match the claims that use them. |
| `property_checks` | 16 passed / 0 failed | `eval/ASMT-001-manyfold-property-checks.json` |
| `ac_pass_rate` | 1.00 | 12/12 nouls ≥ 0.79 |

## LLM-judge rationale

Jev does not emit prose. The typed answers are the rationale.

Score `report_quality` = 2.51, confidence 0.51, nearest level **Excellent** (level 3 of 0–3).

| Question | Noul |
| --- | ---: |
| Grounded | 0.87 |
| Both sides / absent platform recorded | 0.97 |
| Reuse-first | 0.93 |
| Capability ≠ readiness | 0.99 |
| Lenses and conflict | 0.98 |
| Falsification survived | 0.97 |
| Recommendation and confidence | 0.99 |
| Executive stays within findings | 0.79 |
| BLUF first, no TL;DR | 0.80 |
| Objectivity surfaced | 0.98 |
| Precise, harvestable delta named | 0.92 |
| One component table | 0.92 |

Total rating: 4

## Acceptance-criteria checks

| # | Oracle acceptance criterion | Pass? | Evidence / gap |
| --- | --- | :---: | --- |
| AC1 | Grounded, not invented | yes | noul 0.87; ledger C1–C5 |
| AC2 | Both sides read for parity | yes | noul 0.97; platform search recorded as no matches, no "already provides" claim |
| AC3 | Reuse-first inventory present | yes | noul 0.93 |
| AC4 | Capability ≠ readiness | yes | noul 0.99 |
| AC5 | Multi-perspective | yes | noul 0.98 |
| AC6 | Falsified | yes | noul 0.97 |
| AC7 | Justified recommendation + bounded confidence | yes | noul 0.99 |
| AC8 | Executive-legible | yes | noul 0.79 |
| AC9 | BLUF-first, no separate TL;DR | yes | noul 0.80 |
| AC10 | Objectivity surfaced | yes | noul 0.98 |
| AC11 | Precise, not absolute | yes | noul 0.92 |
| AC12 | Table density | yes | noul 0.92 |

## Notes / follow-ups

- PASS bar met: judge score ≥ 0.75, property checks clean, AC pass rate 1.0, faithfulness 1.0, oracle not generator-coupled.
- Spread on the quality score (0.31 on "mostly helpful") is why confidence on that Score is 0.51. The integer rating still rounds to 4. No FAIL signal.
- Branded PDF was not required for the verdict. Render only if `pandoc` is available.
