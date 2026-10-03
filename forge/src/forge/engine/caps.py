"""Caps (ADR D-2) and the typed failures they raise. Every check fails closed."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, fields

# Readers consume input in blocks of up to this size, so a member's measured compressed delta
# can be 0 when its bytes were read ahead with the previous member. The per-member ratio check
# adds one block of slack so a compressible-but-legit member never looks like a bomb.
READ_AHEAD_SLACK = 1 << 20


@dataclass(frozen=True)
class Caps:
    depth: int = 3  # source archive = depth 1
    ratio: int = 200  # uncompressed / compressed
    member_bytes: int = 8 << 30
    total_bytes: int = 64 << 30  # uncompressed bytes across the whole container tree
    spool_bytes: int = (
        24 << 30
    )  # live nested-archive spool + fallback extraction on scratch
    wall_seconds: int = 5400
    # Ratio checks apply only past this many uncompressed bytes (tiny highly-compressible
    # files such as empty text or padding are not bombs).
    ratio_floor_bytes: int = 16 << 20
    # Address-space limit (RLIMIT_AS) of the isolated reader process: an enormous 7z/RAR
    # dictionary fails as ``oom`` instead of OOM-killing the worker pod. 0 disables.
    memory_bytes: int = 1536 << 20
    # Grace after wall_seconds before the parent SIGKILLs a reader stuck inside one call.
    kill_grace_seconds: int = 30

    @classmethod
    def from_env(cls, prefix: str = "FORGE_CAP_") -> Caps:
        """Defaults overridden by ``FORGE_CAP_<FIELD>`` integers (tests / emergency tuning)."""
        kw = {}
        for f in fields(cls):
            raw = os.environ.get(prefix + f.name.upper())
            if raw is not None and raw.strip():
                kw[f.name] = int(raw)
        return cls(**kw)


class EngineFailure(Exception):
    """A typed container failure. ``fatal`` failures abort the whole tree (every ancestor fails
    with the same reason); local failures fail only the container being read."""

    fatal = False

    def __init__(self, reason: str, detail: str | None = None) -> None:
        super().__init__(reason if detail is None else f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class LocalFailure(EngineFailure):
    fatal = False


class FatalFailure(EngineFailure):
    fatal = True


class Budget:
    """Tree-wide accounting shared by every container opened under one ``process()`` call."""

    def __init__(
        self, caps: Caps, top_compressed: int, started: float | None = None
    ) -> None:
        self.caps = caps
        self.started = time.monotonic() if started is None else started
        self.deadline = self.started + caps.wall_seconds
        self.top_compressed = max(top_compressed, 1)
        self.tree_bytes = 0
        self.live_spool = 0
        self.max_depth = 0

    def check_time(self) -> None:
        if time.monotonic() > self.deadline:
            raise FatalFailure(
                "timeout", f"wall time {self.caps.wall_seconds}s exceeded"
            )

    def remaining_seconds(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def add_tree_bytes(self, n: int) -> None:
        self.tree_bytes += n
        caps = self.caps
        if self.tree_bytes > caps.total_bytes:
            raise FatalFailure(
                "total_too_large", f"> {caps.total_bytes} uncompressed bytes"
            )
        if self.tree_bytes > max(
            caps.ratio_floor_bytes, caps.ratio * self.top_compressed
        ):
            raise FatalFailure(
                "ratio_exceeded",
                f"tree {self.tree_bytes} B from {self.top_compressed} B compressed",
            )

    def check_member(self, size: int, compressed: int | None) -> None:
        caps = self.caps
        if size > caps.member_bytes:
            raise LocalFailure("member_too_large", f"> {caps.member_bytes} bytes")
        if compressed is not None and size > max(
            caps.ratio_floor_bytes, caps.ratio * (compressed + READ_AHEAD_SLACK)
        ):
            # A bomb anywhere makes the whole source archive hostile: fatal, not local.
            raise FatalFailure(
                "ratio_exceeded", f"member {size} B from ~{compressed} B compressed"
            )

    def check_container(self, size: int, compressed: int) -> None:
        caps = self.caps
        if size > max(caps.ratio_floor_bytes, caps.ratio * max(compressed, 1)):
            raise FatalFailure(
                "ratio_exceeded", f"container {size} B from {compressed} B compressed"
            )

    def reserve_spool(self, n: int) -> bool:
        if self.live_spool + n > self.caps.spool_bytes:
            return False
        self.live_spool += n
        return True

    def release_spool(self, n: int) -> None:
        self.live_spool = max(0, self.live_spool - n)
