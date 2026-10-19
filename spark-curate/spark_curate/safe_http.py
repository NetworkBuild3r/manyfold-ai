"""HTTP rules shared by every external merge-judge provider.

Bearer tokens must never be resent to another host or sent in cleartext, and vendor
text that reaches logs or audit files must be short and free of control characters.
"""
from __future__ import annotations

import ipaddress
import re
import urllib.parse
import urllib.request
from typing import Any

from .clients import HttpError

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: the default handler would resend the bearer token."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise HttpError("redirect refused")


OPENER = urllib.request.build_opener(NoRedirect)


def _is_lan_ip(host: str | None) -> bool:
    """A private-network IP literal (RFC1918, ULA, link-local). Never loopback: a provider
    on the container's own loopback is not a real provider (llm-no-localhost-provider)."""
    try:
        ip = ipaddress.ip_address(host or "")
    except ValueError:
        return False
    return (ip.is_private or ip.is_link_local) and not ip.is_loopback


def check_base_url(base_url: str) -> None:
    """https only; plain http is allowed solely for a private LAN IP (token stays on the LAN)."""
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme == "https" or (parsed.scheme == "http" and _is_lan_ip(parsed.hostname)):
        return
    raise HttpError("base URL must use https (plain http only for a private LAN IP)")


def short(text: str, limit: int = 120) -> str:
    """Vendor text for logs and audit files: no control characters, capped."""
    return _CONTROL_CHARS.sub(" ", text).strip()[:limit]
