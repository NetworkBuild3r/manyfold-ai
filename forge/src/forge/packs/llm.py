"""OpenAI-compatible chat client for the forge LLM judges (packs + classify + tags).

The endpoint comes from FORGE_LLM_URL only: unset, blank, loopback or a non-http(s) URL raises
LlmConfigError before any work (GR-003, llm-no-localhost-provider); there is no default URL.

The model is *not* a brittle setting. The served model changes regularly, so FORGE_LLM_MODEL is
optional and is checked against ``GET {url}/models`` (see :func:`resolve_model`):

* set and served                       -> use it;
* set, not served, exactly one served  -> use the served one and warn with both names;
* unset / ``auto``, exactly one served -> use it; several or none -> LlmConfigError (ids listed);
* ``/models`` unreachable              -> use the explicit model as given (no guess); unset ->
  LlmConfigError.

A chat reply of HTTP 404 (model not found) re-resolves once and retries with the served model.
The model is **not** part of any cache key (fingerprints hash the input and the prompt only); it
is recorded in the ``model`` column of every decision row for audit.

Every request is schema-bound (response_format json_schema, strict) at temperature 0.

INIT-032/SPEC-010 · model auto-resolve INIT-032/SPEC-016
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from forge.config import optional_env

MAX_CONCURRENCY = 4
OPEN_TIMEOUT = 10.0
READ_TIMEOUT = 180.0
MODELS_TIMEOUT = 5.0
AUTO_MODEL = "auto"
_LOOPBACK = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}
_log = logging.getLogger("forge.llm")


class LlmConfigError(RuntimeError):
    """FORGE_LLM_URL / FORGE_LLM_MODEL missing or invalid, or the model cannot be resolved."""


def validate_url(raw: str | None) -> str:
    """The configured endpoint URL, or LlmConfigError: unset, non-http(s) or loopback."""
    if not raw:
        raise LlmConfigError("FORGE_LLM_URL is not configured; there is no default endpoint")
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        raise LlmConfigError("FORGE_LLM_URL is not a valid http(s) URL")
    if host in _LOOPBACK or host.startswith("127."):
        raise LlmConfigError("FORGE_LLM_URL must not point at localhost / loopback")
    return raw.rstrip("/")


def list_served_models(url: str, *, timeout: float = MODELS_TIMEOUT) -> list[str] | None:
    """Model ids from ``GET {url}/models`` (OpenAI shape), or ``None`` when the endpoint cannot
    answer (transport error, non-200, not JSON, wrong shape). ``[]`` means it answered with none."""
    req = urllib.request.Request(f"{url.rstrip('/')}/models", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            envelope = json.loads(resp.read().decode("utf-8", "replace"))
    except (OSError, ValueError):  # URLError / timeouts / refused / bad JSON
        return None
    data = envelope.get("data") if isinstance(envelope, dict) else None
    if not isinstance(data, list):
        return None
    ids = [m["id"] for m in data if isinstance(m, dict) and isinstance(m.get("id"), str)]
    return sorted(dict.fromkeys(i for i in ids if i.strip()))


def resolve_model(url: str, requested: str | None) -> tuple[str, str]:
    """Pick the model to send. Returns ``(model, how)``; ``how`` is ``explicit`` (served),
    ``explicit_unverified`` (``/models`` unreachable), ``substituted`` (the one served model
    replaced a stale name) or ``auto`` (the one served model). Raises LlmConfigError otherwise.

    ``requested`` ``None`` / blank / ``auto`` means "whatever is served"."""
    wanted = (requested or "").strip()
    if wanted.casefold() == AUTO_MODEL:
        wanted = ""
    served = list_served_models(url)
    if served is None:
        if wanted:
            _log.warning(
                "llm: GET %s/models is unreachable; using FORGE_LLM_MODEL=%r unverified",
                url,
                wanted,
            )
            return wanted, "explicit_unverified"
        raise LlmConfigError(
            f"FORGE_LLM_MODEL is unset/auto and GET {url}/models is unreachable; "
            "set FORGE_LLM_MODEL or fix the endpoint"
        )
    if wanted and wanted in served:
        return wanted, "explicit"
    if len(served) == 1:
        if wanted:
            _log.warning(
                "llm: FORGE_LLM_MODEL=%r is not served; using the one served model %r",
                wanted,
                served[0],
            )
            return served[0], "substituted"
        return served[0], "auto"
    listing = ", ".join(served) if served else "(none)"
    if wanted:
        raise LlmConfigError(
            f"FORGE_LLM_MODEL={wanted!r} is not served by {url}; served models: {listing}"
        )
    raise LlmConfigError(
        f"FORGE_LLM_MODEL is unset/auto but {url} serves "
        f"{len(served)} models (need exactly one): {listing}"
    )


@dataclass(eq=False)
class LlmEndpoint:
    """URL + the model in use. ``requested`` is what the operator configured (``None`` = auto) and
    is what :meth:`reresolve` resolves again when the server stops knowing the model."""

    url: str
    model: str
    requested: str | None = None
    how: str = "explicit"
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def completions_url(self) -> str:
        return f"{self.url}/chat/completions"

    @classmethod
    def resolve(cls, url: str, requested: str | None = None) -> LlmEndpoint:
        """Endpoint for an already-validated URL: query ``/models`` and pick the model."""
        model, how = resolve_model(url, requested)
        wanted = (requested or "").strip()
        asked = None if not wanted or wanted.casefold() == AUTO_MODEL else wanted
        return cls(url=url.rstrip("/"), model=model, requested=asked, how=how)

    @classmethod
    def from_env(cls) -> LlmEndpoint:
        url = validate_url(optional_env("FORGE_LLM_URL"))
        return cls.resolve(url, optional_env("FORGE_LLM_MODEL"))

    def reresolve(self, failed_model: str) -> bool:
        """The server answered 404 for ``failed_model``. Resolve again (once per failure); True
        when ``self.model`` now names a different model worth retrying with."""
        with self._lock:
            if self.model != failed_model:
                return True  # another worker already switched
            try:
                model, how = resolve_model(self.url, self.requested)
            except LlmConfigError as exc:
                _log.warning("llm: re-resolve after HTTP 404 for %r failed: %s", failed_model, exc)
                return False
            if model == failed_model:
                return False
            _log.warning(
                "llm: HTTP 404 for model %r; re-resolved to %r (%s)", failed_model, model, how
            )
            self.model, self.how = model, how
            return True


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
    """POST the body; return the assistant message content. Retries once on transport / 5xx.

    A 404 means the server no longer knows ``body["model"]``: the endpoint re-resolves the model
    once (``GET /models``) and the request is retried with the served one. That retry does not
    use up an attempt; if nothing better is served the 404 is raised as ``http 404``."""
    last: Exception | None = None
    reresolved = False
    tries = 0
    while tries < max(1, attempts):
        req = urllib.request.Request(
            endpoint.completions_url,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=READ_TIMEOUT) as resp:
                envelope = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            last = LlmCallError(f"http {exc.code}")
            if exc.code == 404 and not reresolved and body.get("model"):
                reresolved = True
                if endpoint.reresolve(str(body["model"])):
                    body = {**body, "model": endpoint.model}
                    continue
            tries += 1
            if 500 <= exc.code <= 599:
                continue
            raise last from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = LlmCallError(f"transport: {type(exc).__name__}")
            tries += 1
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
