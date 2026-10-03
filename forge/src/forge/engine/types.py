"""Engine API types (INIT-032 engine contract). No database imports anywhere in ``forge.engine``."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol

ContainerKind = Literal["archive", "loose_batch"]
Status = Literal["done", "failed"]

# ADR D-2 failure_reason enum (container level).
FAILURE_REASONS = frozenset(
    {
        "depth_exceeded",
        "ratio_exceeded",
        "member_too_large",
        "spool_exceeded",
        "total_too_large",
        "timeout",
        "reader_error",
        "unsupported_format",
        "missing_volume",
        "encrypted",
        "oom",
    }
)

# Sink.refused reasons (member level; recorded in container_notes, never extracted).
REFUSAL_REASONS = frozenset(
    {
        "absolute_path",
        "parent_traversal",
        "control_chars",
        "empty_name",
        "symlink",
        "hardlink",
        "device",
        "fifo",
        "socket",
        "not_regular",
        # loose_batch only
        "vanished",
        "reader_error",
    }
)


@dataclass(frozen=True)
class ContainerRef:
    kind: ContainerKind
    paths: tuple[Path, ...]  # archive: volume set in order; loose_batch: the loose files
    display: str  # for logs only


@dataclass(frozen=True)
class Result:
    """Outcome of one container.

    ``members``/``bytes_read`` count this container's own members (uncompressed bytes hashed);
    nested children report their own counts through ``Sink.nested_result``. ``max_depth`` is the
    deepest container opened anywhere in the tree (source archive = 1, loose batch = 0).
    """

    status: Status
    reason: str | None
    members: int
    bytes_read: int
    max_depth: int
    format: str | None = None  # zip, rar4, rar5, 7z, tar, gzip, bzip2, xz, zstd, ... (from magic)
    reader: str | None = None  # libarchive, 7zz, stream, loose
    detail: str | None = None  # truncated reader message, for logs/notes only
    peak_rss_kb: int | None = None  # isolated reader process peak RSS (top-level results only)

    def __post_init__(self) -> None:
        if self.status == "done" and self.reason is not None:
            raise ValueError("done results carry no reason")
        if self.status == "failed" and self.reason not in FAILURE_REASONS:
            raise ValueError(f"unknown failure reason {self.reason!r}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Result:
        return cls(**d)


class Sink(Protocol):
    """Receives engine output. Implemented by the sweep runner (SPEC-007) to write the DB.

    Ordering guarantees:
    - ``member`` is called only after the whole member was read and hashed (GR-004).
    - for a nested archive: ``member`` -> ``nested_archive`` -> child's calls (chain-prefixed)
      -> ``nested_result`` with the child's own Result.
    - chains are unique within a container; a repeated member path gets ``//dupN`` appended.
    """

    def member(
        self,
        chain: tuple[str, ...],
        sha256: str,
        size: int,
        kind: str,
        triangles: int | None,
        depth: int,
    ) -> None: ...

    def refused(self, chain: tuple[str, ...], reason: str) -> None: ...

    def nested_archive(self, chain: tuple[str, ...], sha256: str, size: int) -> None: ...

    def nested_result(self, chain: tuple[str, ...], result: Result) -> None: ...
