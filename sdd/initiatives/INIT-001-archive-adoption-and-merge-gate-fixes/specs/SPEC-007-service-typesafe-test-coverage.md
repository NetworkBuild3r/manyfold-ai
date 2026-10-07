# SPEC-007 · Service: Hermetic TypeSafe tests + client/fallback coverage

## Metadata

```yaml
spec_id: SPEC-007
initiative_id: INIT-001
title: Hermetic spark-curate merge tests and coverage for the TypeSafe client and fallback paths
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
blocked_by: [SPEC-006]
blocks: None
```

---

## Description

**Context (MAJ-7):**
- `typesafe_client.py` has no tests.
- `decide_merge_pair`'s TypeSafe-failure and vision-failure branches have no tests.
- `api_key_from` falls back to `os.environ["TYPESAFE_API_KEY"]`, so any merge test that reaches the
  TypeSafe branch makes a live, billable call whenever the key is exported. The key is exported inside the
  container via `docker-compose.yml`.

**Scope (in):** Tests only, plus at most a test helper module. No production behavior changes.

## Acceptance Criteria

- [x] ac-1: Every merge-related test module (`test_decide_merge.py`, `test_merge_candidates.py`,
  `test_merge_hitl.py`, `test_typesafe_merge.py`) blanks `TYPESAFE_API_KEY` for the whole module. Use
  `setUpModule`/`tearDownModule` with `patch.dict(os.environ, …)` or a shared helper. A guard test proves
  that `urllib.request.urlopen` is never called by the suite. — covered: yes
- [x] ac-2: `typesafe_client.system_one` tests use a fake `urlopen`. They cover:
  - success;
  - empty key (raises before any request);
  - `HTTPError` (message truncated to 300 chars and **never** containing the API key);
  - `URLError`;
  - non-JSON body;
  - a body missing `answers`.

  `api_key_from` precedence (config over env) is also tested. — covered: yes
- [x] ac-3: `decide_merge_pair` fallback tests cover:
  - TypeSafe raises on a STRONG pair, giving a pending plan with `error` set and approved False;
  - TypeSafe raises on an UNCERTAIN pair, falling back to the curator/Qwen path;
  - UNCERTAIN with previews where Gemma raises, returning an error without calling TypeSafe.

  — covered: yes
- [x] ac-4: `smoke()` tests: with a key set and `system_one` mocked, it exits 0 when all checks pass and 1
  when TypeSafe fails; with no key, it prints SKIP. — covered: yes
- [x] ac-5: The suite passes identically with `TYPESAFE_API_KEY=dummy` exported and with it unset. —
  covered: no

## Deliverables

- [x] `spark-curate/tests/test_typesafe_client.py` (new)
- [x] `spark-curate/tests/test_typesafe_merge.py` (fallback cases)
- [x] `spark-curate/tests/test_decide_merge.py`, `test_merge_candidates.py`, `test_merge_hitl.py`
  (module-level env isolation)
- [x] Optional: `spark-curate/tests/_isolation.py` helper

## Security

- **Sensitivity:** standard. Trigger: secret handling.
- **Security acceptance criteria:**
  - [x] A test asserts the API key string never appears in any raised `HttpError` message (ac-2).

## Verification Strategy

- **Claim:** The spark-curate test suite is hermetic, and every TypeSafe client and fallback branch is
  exercised.
- **Check + executor:** mechanized: `cd spark-curate && TYPESAFE_API_KEY=dummy python -m unittest discover -s tests -v`,
  then the same command with the variable unset.
- **Pass condition:** Both runs are green. The ac-1 guard test (which patches `urlopen` to raise if
  called) passes in the exported run. Each ac-2, ac-3 and ac-4 bullet maps to a named test.

## Integration Points

- Tests the semantics delivered by SPEC-006.
- **Provenance tag:** `INIT-001/SPEC-007`
