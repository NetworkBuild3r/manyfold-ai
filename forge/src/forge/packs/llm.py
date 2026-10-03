"""OpenAI-compatible chat client for the forge LLM judges (packs + classify).

Endpoint and model come from FORGE_LLM_URL / FORGE_LLM_MODEL only: unset, blank, loopback or a
non-http(s) URL raises LlmConfigError before any work (GR-003, llm-no-localhost-provider).
Every request is schema-bound (response_format json_schema, strict) at temperature 0.

INIT-032/SPEC-010
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from forge.config import optional_env

MAX_CONCURRENCY = 4
OPEN_TIMEOUT = 10.0
READ_TIMEOUT = 180.0
_LOOPBACK = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}


class LlmConfigError(RuntimeError):
    """FORGE_LLM_URL / FORGE_LLM_MODEL missing or invalid."""


@dataclass(frozen=True)
class LlmEndpoint:
    url: str
    model: str

    @property
    def completions_url(self) -> str:
        return f"{self.url}/chat/completions"

    @classmethod
    def from_env(cls) -> LlmEndpoint:
        raw = optional_env("FORGE_LLM_URL")
        if not raw:
            raise LlmConfigError("FORGE_LLM_URL is not configured; there is no default endpoint")
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower()
        if parts.scheme not in ("http", "https") or not host:
            raise LlmConfigError("FORGE_LLM_URL is not a valid http(s) URL")
        if host in _LOOPBACK or host.startswith("127."):
            raise LlmConfigError("FORGE_LLM_URL must not point at localhost / loopback")
        model = optional_env("FORGE_LLM_MODEL")
        if not model:
            raise LlmConfigError("FORGE_LLM_MODEL is not configured; there is no default model")
        return cls(url=raw.rstrip("/"), model=model)


def prompt_hash(*parts: Any) -> str:
    """sha256 over the system prompt, schema and version — recorded with every decision."""
    blob = json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()


def request_body(
    endpoint: LlmEndpoint,
    *,
    system: str,
    user: str,
    schema: dict,
    schema_name: str,
    max_tokens: int = 300,
) -> dict:
    return {
        "model": endpoint.model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": schema},
        },
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }


class LlmCallError(RuntimeError):
    pass


def post_json(endpoint: LlmEndpoint, body: dict, *, attempts: int = 2) -> str:
    """POST the body; return the assistant message content. Retries once on transport / 5xx."""
    data = json.dumps(body).encode()
    last: Exception | None = None
    for _ in range(max(1, attempts)):
        req = urllib.request.Request(
            endpoint.completions_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=READ_TIMEOUT) as resp:
                envelope = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            last = LlmCallError(f"http {exc.code}")
            if 500 <= exc.code <= 599:
                continue
            raise last from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = LlmCallError(f"transport: {type(exc).__name__}")
            continue
        except json.JSONDecodeError as exc:
            raise LlmCallError("invalid_envelope_json") from exc
        try:
            content = envelope["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmCallError("invalid_envelope_shape") from exc
        if not isinstance(content, str) or not content.strip():
            raise LlmCallError("empty_content")
        return content
    raise last or LlmCallError("no attempt made")


def strict_object(content: str, required: Iterable[str]) -> dict:
    """Parse content as a JSON object with exactly the required keys (extra/missing → error)."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LlmCallError("invalid_verdict_json") from exc
    if not isinstance(data, dict):
        raise LlmCallError("non_object")
    req = set(required)
    extra = sorted(set(data) - req)
    missing = sorted(req - set(data))
    if extra:
        raise LlmCallError("extra_field:" + ",".join(extra))
    if missing:
        raise LlmCallError("missing_field:" + ",".join(missing))
    return data


def map_concurrent[T, R](
    fn: Callable[[T], R], items: Iterable[T], concurrency: int = MAX_CONCURRENCY
) -> Iterator[tuple[T, R]]:
    """Run fn over items, at most `concurrency` (capped at 4) calls in flight, in input order."""
    workers = max(1, min(MAX_CONCURRENCY, int(concurrency)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending: list = []
        it = iter(items)
        for item in it:
            pending.append((item, pool.submit(fn, item)))
            if len(pending) >= workers * 2:
                head, fut = pending.pop(0)
                yield head, fut.result()
        for head, fut in pending:
            yield head, fut.result()
