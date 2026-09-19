---
spec_id: SPEC-001
title: No runtime Jev; STRONG is not permission
status: complete
spec_domain: docs
initiative: INIT-001-jev-judgments
blocked_by: []
model: sonnet
prompt: .claude/agents/implementation-planner/AGENT.md
plan_only: true
security_review: light
---

# SPEC-001: No runtime Jev; STRONG is not permission

## Summary

Write the contract the service spec implements. Jev is the coding judge for this initiative. The Manyfold Rails app and spark-curate do not call TypeSafe. The product change is that a STRONG pair is a plan, not an approval, and it goes through the Gemma vision path that non-STRONG pairs already use.

## Dependencies

None. Blocks SPEC-002.

## Deliverables

- `sdd/initiatives/INIT-001-jev-judgments/decision-jev-judgments.md` containing:
  1. No `typesafe` module, import, or `TYPESAFE_API_KEY` read in `app/` or `spark-curate/`.
  2. Jev may be called by the coding agent during orchestration and review. Those calls stay outside the product process.
  3. `decide_merge_pair` must not return `_strong_merge_decision` before vision (`origin/main` lines 203–205, confidence 0.85 at line 171).
  4. Code gates that stay: franchise-only refuse (line 199); preview-less refuse; `approved_for_apply` false unless both previews produced text and the existing curator decision is merge; `MERGE_HITL` default `hitl_all` queues nothing.
  5. Out of scope: `ModelFile#duplicate?`, `Problems::Duplicate`, NudeNet, organize-mode `VISION_PROMPT`.

## Acceptance Criteria

- [ ] The page exists and states all five points as sentences.
- [ ] It does not instruct anyone to add a TypeSafe client.
- [ ] It cites `decide_merge.py` lines 164, 171, and 203.

## Controls & Gates

- **Autonomy level:** plan_only. Write the markdown file on this branch.
- **Gate actions triggered:** none.
- **Blocking checks:** the five points are present.
- **Rollback:** delete the page.

## Security

- **Sensitivity:** light. Triggers: none. The page must not contain a secret.
- **Review depth:** quick · **focus areas:** no API key, no Authorization example with a real value.

## Verification Strategy

- **Claim:** the decision page forbids a TypeSafe client in the product and forbids treating STRONG as permission.
- **Check + executor:** mechanized — `rg -n "TYPESAFE|typesafe|0.85|franchise-only" sdd/initiatives/INIT-001-jev-judgments/decision-jev-judgments.md` matches each pattern. Human — the SPEC-002 implementer can follow point 4 without asking what "approved" means.
- **Pass condition:** all four patterns match, and the page says `approved_for_apply` is false when either preview text is missing.

## Open Questions

None.
