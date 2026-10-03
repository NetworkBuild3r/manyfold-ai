"""Member-name and member-type refusal (hostile members are recorded, never extracted)."""

from __future__ import annotations

import re

AE_IFMT = 0o170000
AE_IFREG = 0o100000
AE_IFLNK = 0o120000
AE_IFSOCK = 0o140000
AE_IFCHR = 0o020000
AE_IFBLK = 0o060000
AE_IFDIR = 0o040000
AE_IFIFO = 0o010000

_DRIVE = re.compile(r"^[A-Za-z]:")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def decode_name(raw: bytes) -> str:
    """Archive names are bytes of unknown charset: UTF-8 when valid, else escaped bytes.

    The result never contains surrogates, so it is safe for JSON and Postgres text.
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="backslashreplace")


def display_name(name: str) -> str:
    """Name with control characters escaped (``\\xNN``) for refusal notes."""
    return _CONTROL.sub(lambda m: f"\\x{ord(m.group()):02x}", name)


def check_name(name: str) -> tuple[str | None, str | None]:
    """``(normalized_path, None)`` for an acceptable member name, else ``(None, reason)``.

    Backslash is treated as a separator (Windows-made archives). ``.`` and empty segments are
    dropped; a ``..`` segment, a leading separator, a drive letter, or any control character
    (including NUL) is refused.
    """
    if _CONTROL.search(name):
        return None, "control_chars"
    unified = name.replace("\\", "/")
    if unified.startswith("/") or _DRIVE.match(unified):
        return None, "absolute_path"
    parts = [p for p in unified.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None, "parent_traversal"
    if not parts:
        return None, "empty_name"
    return "/".join(parts), None


def check_filetype(filetype: int, hardlink: bool, symlink: bool) -> str | None:
    """Refusal reason for a non-regular member, ``None`` for a regular file.

    Directories are not refused (callers skip them before calling this).
    """
    if symlink:
        return "symlink"
    if hardlink:
        return "hardlink"
    ft = filetype & AE_IFMT
    if ft == AE_IFREG or ft == 0:  # some zip/rar readers report 0 for plain files
        return None
    if ft == AE_IFLNK:
        return "symlink"
    if ft in (AE_IFCHR, AE_IFBLK):
        return "device"
    if ft == AE_IFIFO:
        return "fifo"
    if ft == AE_IFSOCK:
        return "socket"
    return "not_regular"
