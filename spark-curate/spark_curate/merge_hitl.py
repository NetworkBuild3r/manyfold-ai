"""Graduated MERGE_HITL apply policy (INIT-018/SPEC-006 — ADR D-6).

Modes:
  hitl_all       — default; plans only (never auto-queue to pending)
  hitl_uncertain — auto-queue STRONG approved_for_apply only
  hitl_off       — also auto-queue UNCERTAIN when approved_for_apply

Never auto-apply REFUSE / keep_separate / missing-preview weak (those are
keep_separate from decide_merge). Invalid MERGE_HITL fails loud.
"""
from __future__ import annotations

from typing import Literal

from .decide_merge import MergeDecision, _is_strong_structural

MergeHitlMode = Literal["hitl_all", "hitl_uncertain", "hitl_off"]
HitlBand = Literal["STRONG", "UNCERTAIN", "REFUSE"]

MERGE_HITL_VALUES: frozenset[str] = frozenset(
    {"hitl_all", "hitl_uncertain", "hitl_off"}
)
DEFAULT_MERGE_HITL: MergeHitlMode = "hitl_all"


class InvalidMergeHitlError(ValueError):
    """Raised when MERGE_HITL is not one of the three allowed modes."""


def parse_merge_hitl(value: str | None) -> MergeHitlMode:
    """
    Resolve MERGE_HITL from env/config.

    None / blank → hitl_all (safe default).
    Any other unrecognized value → fail loud (never coerce to hitl_off).
    """
    if value is None:
        return DEFAULT_MERGE_HITL
    raw = str(value).strip()
    if not raw:
        return DEFAULT_MERGE_HITL
    if raw not in MERGE_HITL_VALUES:
        allowed = ", ".join(sorted(MERGE_HITL_VALUES))
        raise InvalidMergeHitlError(
            f"Invalid MERGE_HITL={raw!r}; expected one of: {allowed} "
            f"(default {DEFAULT_MERGE_HITL!r}; never coerce to hitl_off)"
        )
    return raw  # type: ignore[return-value]


def classify_hitl_band(decision: MergeDecision) -> HitlBand:
    """
    Map a MergeDecision to the HITL band for apply policy.

    STRONG = deterministic structural band (shared_digest or ≥T mesh overlap),
    not Gemma confidence alone. Non-merge / keep_separate → REFUSE.
    merge without STRONG signals → UNCERTAIN.
    """
    if decision.decision != "merge":
        return "REFUSE"
    if _is_strong_structural(list(decision.signals)):
        return "STRONG"
    return "UNCERTAIN"


def should_auto_apply(decision: MergeDecision, merge_hitl: str) -> bool:
    """
    Whether this decision may be queued to merges-pending.jsonl under APPLY=1.

    Requires decision==merge and approved_for_apply. Band × mode matrix:

    | Mode           | STRONG | UNCERTAIN | REFUSE |
    | hitl_all       | no     | no        | no     |
    | hitl_uncertain | yes*   | no        | no     |
    | hitl_off       | yes*   | yes*      | no     |

    (*) only when approved_for_apply is True.
    """
    mode = parse_merge_hitl(merge_hitl)
    if decision.decision != "merge":
        return False
    if not decision.approved_for_apply:
        return False

    band = classify_hitl_band(decision)
    if band == "REFUSE":
        return False
    if mode == "hitl_all":
        return False
    if mode == "hitl_uncertain":
        return band == "STRONG"
    # hitl_off
    return band in {"STRONG", "UNCERTAIN"}
