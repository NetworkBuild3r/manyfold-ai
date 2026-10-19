"""TypeSafe System One client (stdlib HTTP).

Credentials stay in TYPESAFE_API_KEY / config; never log the key or put it
in exception messages. Jev is text-only — images stay on Gemma.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from . import safe_http
from .clients import HttpError

DEFAULT_BASE_URL = "https://api.typesafe.ai"
DEFAULT_MODEL = "jev-latest"


# Shared rules (no redirects, https only, short vendor text) live in safe_http.
_NoRedirect = safe_http.NoRedirect
_OPENER = safe_http.OPENER
_check_base_url = safe_http.check_base_url
_short = safe_http.short


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
