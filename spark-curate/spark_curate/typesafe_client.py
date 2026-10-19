"""TypeSafe System One client (stdlib HTTP).

Credentials stay in TYPESAFE_API_KEY / config; never log the key or put it
in exception messages. Jev is text-only — images stay on Gemma.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .clients import HttpError

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: the default handler would resend the bearer token."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise HttpError("TypeSafe redirect refused")


_OPENER = urllib.request.build_opener(_NoRedirect)


def api_key_from(curate: Any | None = None) -> str:
    """Prefer the environment, then config. Empty means TypeSafe is not configured.

    The environment wins so a rotated secret is never shadowed by a stale key
    left in a config file.
    """
    from_env = str(os.environ.get("TYPESAFE_API_KEY") or "").strip()
    if from_env:
        return from_env
    if curate is not None:
        return str(getattr(curate, "typesafe_api_key", "") or "").strip()
    return ""


def _check_base_url(base_url: str) -> None:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in _LOCAL_HOSTS):
        return
    raise HttpError("TypeSafe base URL must use https")


def _short(text: str, limit: int = 120) -> str:
    """Vendor text for logs and audit files: no control characters, capped."""
    return _CONTROL_CHARS.sub(" ", text).strip()[:limit]


def system_one(
    *,
    api_key: str,
    state: Any,
    questions: dict[str, Any],
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """POST /v1/systemone and return the parsed JSON body."""
    if not api_key:
        raise HttpError("TypeSafe API key is not configured")
    _check_base_url(base_url)
    url = base_url.rstrip("/") + "/v1/systemone"
    payload = {
        "state": state,
        "model": model,
        "questions": questions,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            out = json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace").replace(api_key, "[redacted]")
        raise HttpError(f"HTTP {e.code} TypeSafe systemone: {_short(err)}") from e
    except urllib.error.URLError as e:
        raise HttpError(f"TypeSafe connection failed: {e}") from e
    except json.JSONDecodeError as e:
        raise HttpError("TypeSafe returned non-JSON") from e
    if not isinstance(out, dict) or "answers" not in out:
        keys = sorted(out)[:10] if isinstance(out, dict) else type(out).__name__
        raise HttpError(f"Unexpected TypeSafe response (keys: {keys})")
    return out
