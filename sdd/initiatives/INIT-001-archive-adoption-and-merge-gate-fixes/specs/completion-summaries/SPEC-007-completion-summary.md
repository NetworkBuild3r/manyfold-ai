# SPEC-007 Completion Summary — Hermetic TypeSafe tests + client/fallback coverage

**Provenance:** `INIT-001/SPEC-007` · **Completed:** 2026-10-07 · **Findings closed:** MAJ-7

## Changes
- `tests/_isolation.py` (new): module hooks that blank `TYPESAFE_API_KEY` and replace
  `urllib.request.urlopen` with a refusal that raises `NetworkCallInTest`. It is a `BaseException`, so
  production `except Exception` blocks cannot swallow it. Wired into `test_decide_merge.py`,
  `test_merge_candidates.py`, `test_merge_hitl.py`, `test_typesafe_merge.py` and `test_typesafe_client.py`.
- `tests/test_typesafe_client.py` (new, 9 tests): success payload and headers, empty key, HTTP error
  (truncated, key redacted), URLError, non-JSON, missing `answers`, and `api_key_from` precedence.
- `tests/test_typesafe_merge.py`: isolation guard test, three fallback tests (STRONG + TypeSafe failure;
  UNCERTAIN + TypeSafe failure → Qwen; UNCERTAIN + Gemma failure → no TypeSafe), and three `smoke()` tests.

## Deviation from scope ("tests only")
- `spark_curate/typesafe_client.py`: one-line production change. The HTTP error body now replaces the API
  key with `[redacted]` before going into the exception message. ac-2 required that the key never appear
  in a raised message, and a server that echoes the key back would otherwise leak it into
  `MergeDecision.error` and the audit JSONL.

## Verification
- `env -u TYPESAFE_API_KEY python -m unittest discover -s tests`: 79 tests, OK.
- `TYPESAFE_API_KEY=dummy python -m unittest discover -s tests`: 79 tests, OK.
- `ruff check tests spark_curate/typesafe_client.py`: clean.
