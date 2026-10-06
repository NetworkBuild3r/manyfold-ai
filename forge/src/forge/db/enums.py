"""Postgres-backed enums for the forge catalog.

INIT-032/SPEC-004 · ADR D-1 / D-2 · engine-contract schema notes
"""

from __future__ import annotations

import enum


class SourceFileKind(enum.StrEnum):
    archive = "archive"
    loose = "loose"


class ContainerKind(enum.StrEnum):
    archive = "archive"
    loose_batch = "loose_batch"
    nested = "nested"


class ContainerStatus(enum.StrEnum):
    pending = "pending"
    claimed = "claimed"
    done = "done"
    failed = "failed"


class FailureReason(enum.StrEnum):
    """ADR D-2 caps plus SPEC-007 retries_exhausted."""

    depth_exceeded = "depth_exceeded"
    ratio_exceeded = "ratio_exceeded"
    member_too_large = "member_too_large"
    spool_exceeded = "spool_exceeded"
    total_too_large = "total_too_large"
    timeout = "timeout"
    reader_error = "reader_error"
    unsupported_format = "unsupported_format"
    missing_volume = "missing_volume"
    encrypted = "encrypted"
    oom = "oom"
    retries_exhausted = "retries_exhausted"


class BlobKind(enum.StrEnum):
    mesh = "mesh"
    image = "image"
    archive = "archive"
    doc = "doc"
    other = "other"


class SweepKind(enum.StrEnum):
    walk = "walk"
    sweep = "sweep"


class PackStatus(enum.StrEnum):
    provisional = "provisional"
    resolved = "resolved"
    materialized = "materialized"


class PackContainerRole(enum.StrEnum):
    primary = "primary"
    source = "source"
    absorbed = "absorbed"


class PackDecisionKind(enum.StrEnum):
    deterministic = "deterministic"
    llm = "llm"
    human = "human"


class PackVerdict(enum.StrEnum):
    same_pack = "same_pack"
    separate = "separate"
    unsure = "unsure"
    absorb = "absorb"


PACK_CATEGORIES = (
    "Anime",
    "Cartoons",
    "Cosplay",
    "DC",
    "D&D",
    "Games",
    "Movie TV",
    "Comics",
    "Vehicles",
    "Terrain",
    "Tabletop",
    "Art",
    "Tools",
    "Misc",
)
