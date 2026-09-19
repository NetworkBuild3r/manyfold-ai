# Decision: Jev is a coding judge, STRONG is not permission

Initiative: INIT-001-jev-judgments. Charter SHA: `origin/main` `8445b75`.

## 1. No TypeSafe in the product

The Manyfold Rails app (`app/`) and the curator (`spark-curate/`) do not gain a `typesafe` module, a `typesafe` import, or a read of `TYPESAFE_API_KEY`. That key stays in the coding agent's environment. It is not written into config JSON, logs, or git.

## 2. Jev while coding only

Jev (`jev-latest`, `POST /v1/systemone`) may be called by the coding agent during orchestration, acceptance checks, and review. Those calls run outside the Manyfold process and outside the curator process. A product code path must not call them.

## 3. STRONG is not a shortcut

`decide_merge_pair` must not return `_strong_merge_decision` before vision. On `origin/main` that shortcut is `spark-curate/spark_curate/decide_merge.py:203`, which calls `_strong_merge_decision` defined at line 164 and sets confidence to 0.85 at line 171. A STRONG pair is a plan. It uses the existing Gemma vision call, the same one non-STRONG pairs already use when both previews exist.

## 4. Code gates

A franchise-only pair is refused: no structural duplicate signal means keep separate (`decide_merge.py` around line 199). A missing preview on either folder sets `approved_for_apply` false. `approved_for_apply` is also false when vision or the existing curator call fails. It is true only when both previews produced text and the existing curator decision is merge. `MERGE_HITL` default `hitl_all` queues nothing, including a pair the curator called merge.

## 5. Out of scope

`ModelFile#duplicate?`, `Problems::Duplicate`, NudeNet, and organize-mode `VISION_PROMPT` do not change. This page does not add a TypeSafe client.
