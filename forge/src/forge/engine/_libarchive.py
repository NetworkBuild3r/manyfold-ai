"""Minimal ctypes binding to libarchive.so.13 for multi-volume streaming reads.

``libarchive-c`` locates the library (``$LIBARCHIVE`` or ``find_library``); this module binds its
own function objects on that path so volume sets can be opened with
``archive_read_open_filenames`` (one logical stream across all volumes).
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER, c_char_p, c_int, c_int64, c_size_t, c_ssize_t, c_void_p
from dataclasses import dataclass
from os import fsencode
from pathlib import Path
from typing import Self

from libarchive import ffi as _lc_ffi

ARCHIVE_EOF = 1
ARCHIVE_OK = 0
ARCHIVE_WARN = -20

_lib = ctypes.CDLL(_lc_ffi.libarchive_path)


def _bind(name: str, restype, *argtypes):
    fn = getattr(_lib, name)
    fn.restype = restype
    fn.argtypes = list(argtypes)
    return fn


_read_new = _bind("archive_read_new", c_void_p)
_support_filter_all = _bind("archive_read_support_filter_all", c_int, c_void_p)
_support_format_all = _bind("archive_read_support_format_all", c_int, c_void_p)
_open_filenames = _bind(
    "archive_read_open_filenames", c_int, c_void_p, POINTER(c_char_p), c_size_t
)
_next_header = _bind("archive_read_next_header", c_int, c_void_p, POINTER(c_void_p))
_read_data = _bind("archive_read_data", c_ssize_t, c_void_p, c_void_p, c_size_t)
_read_free = _bind("archive_read_free", c_int, c_void_p)
_error_string = _bind("archive_error_string", c_char_p, c_void_p)
_errno = _bind("archive_errno", c_int, c_void_p)
_format_name = _bind("archive_format_name", c_char_p, c_void_p)
_filter_bytes = _bind("archive_filter_bytes", c_int64, c_void_p, c_int)
_e_pathname = _bind("archive_entry_pathname", c_char_p, c_void_p)
_e_filetype = _bind("archive_entry_filetype", c_int, c_void_p)
_e_size = _bind("archive_entry_size", c_int64, c_void_p)
_e_size_is_set = _bind("archive_entry_size_is_set", c_int, c_void_p)
_e_symlink = _bind("archive_entry_symlink", c_char_p, c_void_p)
_e_hardlink = _bind("archive_entry_hardlink", c_char_p, c_void_p)
_e_is_encrypted = _bind("archive_entry_is_encrypted", c_int, c_void_p)

version_string = _bind("archive_version_string", c_char_p)().decode()


class LibarchiveError(Exception):
    def __init__(self, message: str, code: int = 0, errno: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.errno = errno


@dataclass(frozen=True)
class Entry:
    raw_name: bytes
    filetype: int
    size: int | None
    symlink: bool
    hardlink: bool
    encrypted: bool


class Reader:
    """One sequential pass over an archive (or a volume set opened as one stream)."""

    def __init__(
        self, paths: list[Path] | tuple[Path, ...], block_size: int = 1 << 20
    ) -> None:
        self._a = _read_new()
        if not self._a:
            raise MemoryError("archive_read_new failed")
        _support_filter_all(self._a)
        _support_format_all(self._a)
        names = [fsencode(str(p)) for p in paths]
        self._names = (c_char_p * (len(names) + 1))(*names, None)
        rc = _open_filenames(self._a, self._names, block_size)
        if rc != ARCHIVE_OK:
            err = self._error(rc)
            self.close()
            raise err
        self._entry = c_void_p()

    def _error(self, rc: int) -> LibarchiveError:
        msg = _error_string(self._a) if self._a else None
        text = msg.decode("utf-8", "replace") if msg else f"libarchive error {rc}"
        return LibarchiveError(text, rc, _errno(self._a) if self._a else 0)

    def next(self) -> Entry | None:
        rc = _next_header(self._a, ctypes.byref(self._entry))
        if rc == ARCHIVE_EOF:
            return None
        if rc not in (ARCHIVE_OK, ARCHIVE_WARN):
            raise self._error(rc)
        e = self._entry
        raw = _e_pathname(e) or b""
        return Entry(
            raw_name=raw,
            filetype=_e_filetype(e) & 0o170000,
            size=_e_size(e) if _e_size_is_set(e) else None,
            symlink=bool(_e_symlink(e)),
            hardlink=bool(_e_hardlink(e)),
            encrypted=bool(_e_is_encrypted(e)),
        )

    def read_into(self, buf, size: int) -> int:
        n = _read_data(self._a, buf, size)
        if n < 0:
            raise self._error(n)
        return n

    def compressed_bytes(self) -> int:
        """Bytes consumed from the raw input so far (all volumes)."""
        return int(_filter_bytes(self._a, -1))

    def format_name(self) -> str | None:
        name = _format_name(self._a)
        return name.decode("utf-8", "replace") if name else None

    def close(self) -> None:
        if self._a:
            _read_free(self._a)
            self._a = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
