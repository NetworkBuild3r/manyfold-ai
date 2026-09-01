"""Vision-based merge decision for a candidate pair.

Provenance: INIT-018/SPEC-003 — close preview-less name-only auto-merge (ADR D-5);
typed STRONG / UNCERTAIN / REFUSE bands (ADR D-4); franchise hard gate (ADR D-7).
INIT-018/SPEC-005 — archive_member_overlap:N / shared_archive_member STRONG recognition.
INIT-018/SEC-018-02 — multi-file shared_digest:N (N≥2) for digest STRONG.
"""
from __future__ import annotations

import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import clients
from .candidates import DEFAULT_MESH_OVERLAP_T, MergeCandidate
from .config import CurateConfig, SparkConfig
from .decide import _sample_files
from .preview import best_image, load_image_as_jpeg_bytes, try_extract_preview_from_zip

# Re-export for callers / tests (canonical default lives on candidates — INIT-018/SPEC-005).

MERGE_VISION_PROMPT = """You decide whether two Manyfold model folders should be MERGED into one inventory entry.

Merge ONLY if they are the same printable product: duplicate download, renamed copy, or an obvious split of one pack.
Same character or franchise with DIFFERENT sculpts, poses, scales, or artists = keep_separate.
Two Batmans that look different = keep_separate. Never merge just because the name shares a character.

Folder A:
- path: {path_a}
- files (sample): {files_a}

Folder B:
- path: {path_b}
- files (sample): {files_b}

Candidate signals from the filesystem (not proof alone): {signals}

Image 1 = preview of A. Image 2 = preview of B.

Return ONLY JSON (no markdown):
{{
  "decision": "merge" | "keep_separate",
  "confidence": 0.0,
  "target": "a" | "b",
  "reason": "one short sentence"
}}

Rules:
- target = which folder should remain as the Manyfold model after merge (prefer the better-named / more-complete one).
- confidence 0..1. Use >= 0.80 only when you are sure they are the same product.
- If unsure, decision=keep_separate with confidence < 0.80.
"""


MERGE_CURATOR_SYSTEM = """Normalize merge-decision JSON. Output ONLY valid JSON:
{
  "decision": "merge"|"keep_separate",
  "confidence": number,
  "target": "a"|"b",
  "reason": string
}
If input is garbage: decision=keep_separate, confidence=0, target=a, reason="parse_failed".
"""


@dataclass
class MergeDecision:
    path_a: str
    path_b: str
    rel_a: str
    rel_b: str
    decision: str  # merge | keep_separate
    confidence: float
    target: str  # a | b
    reason: str
    signals: list[str]
    approved_for_apply: bool
    error: str | None = None
    raw_vision: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _preview_jpeg(
    folder_path: Path,
    thumb_cache: Path,
    curate: CurateConfig,
) -> bytes | None:
    thumb = best_image(folder_path)
    if thumb is None:
        thumb = try_extract_preview_from_zip(folder_path, thumb_cache)
    if thumb is None:
        return None
    try:
        return load_image_as_jpeg_bytes(thumb, curate.max_image_edge, curate.jpeg_quality)
    except OSError:
        return None


def _archive_member_overlap(signals: list[str]) -> int:
    """Parse archive_member_overlap:N from SPEC-005 signal stubs (0 if absent/invalid)."""
    for s in signals:
        if s.startswith("archive_member_overlap:"):
            try:
                return int(s.split(":", 1)[1])
            except ValueError:
                return 0
    return 0


def _shared_digest_count(signals: list[str]) -> int:
    """
    Distinct shared loose-file digests (SEC-018-02 / ADR D-4).

    Prefers counted ``shared_digest:N``. Bare legacy ``shared_digest`` counts as 1
    (not multi-file → not STRONG).
    """
    for s in signals:
        if s.startswith("shared_digest:"):
            try:
                return int(s.split(":", 1)[1])
            except ValueError:
                return 0
    if "shared_digest" in signals:
        return 1
    return 0


def _has_structural_signal(signals: list[str]) -> bool:
    """True when a non-franchise filesystem/archive signal is present (ADR D-7)."""
    return any(
        s == "name_near_dupe"
        or s == "shared_digest"
        or s.startswith("shared_digest:")
        or s == "shared_archive_member"
        or s.startswith("basename_size_overlap")
        or s.startswith("archive_member_overlap:")
        for s in signals
    )


def _is_strong_structural(
    signals: list[str],
    *,
    mesh_t: int = DEFAULT_MESH_OVERLAP_T,
) -> bool:
    """
    STRONG band (ADR D-4 / INIT-018/SPEC-005 / SEC-018-02): multi-file
    shared_digest (≥2 distinct digests), or ≥T distinct mesh archive overlaps.

    Not STRONG: single shared_digest; name_near_dupe alone; archive overlap < T;
    (≥1 large mesh + name_near_dupe) — those are UNCERTAIN (or keep_separate
    when preview-less — ADR D-5).
    """
    if _shared_digest_count(signals) >= 2:
        return True
    if _archive_member_overlap(signals) >= mesh_t:
        return True
    return False


def _strong_merge_decision(
    base: MergeDecision,
    cand: MergeCandidate,
    curate: CurateConfig,
) -> MergeDecision:
    """Deterministic STRONG merge — skip Gemma (ADR D-4). Confidence ≥ min_merge_confidence."""
    base.decision = "merge"
    base.confidence = 0.85
    base.target = "a" if len(cand.a.name) <= len(cand.b.name) else "b"
    base.reason = "STRONG structural duplicate; skip Gemma"
    base.approved_for_apply = base.confidence >= curate.min_merge_confidence
    return base


def decide_merge_pair(
    cand: MergeCandidate,
    spark: SparkConfig,
    curate: CurateConfig,
    thumb_cache: Path,
) -> MergeDecision:
    signals = list(cand.signals)
    base = MergeDecision(
        path_a=str(cand.a.path),
        path_b=str(cand.b.path),
        rel_a=cand.a.rel_posix,
        rel_b=cand.b.rel_posix,
        decision="keep_separate",
        confidence=0.0,
        target="a",
        reason="",
        signals=signals,
        approved_for_apply=False,
    )

    # Hard gate: franchise/character alone is never enough — need at least one structural signal
    if not _has_structural_signal(signals):
        base.reason = "no structural duplicate signal; refuse franchise-only merge"
        return base

    # STRONG: deterministic plan, no Gemma — even when previews are missing (ADR D-5 / aud-1)
    if _is_strong_structural(signals):
        return _strong_merge_decision(base, cand, curate)

    jpeg_a = _preview_jpeg(cand.a.path, thumb_cache, curate)
    jpeg_b = _preview_jpeg(cand.b.path, thumb_cache, curate)
    if jpeg_a is None or jpeg_b is None:
        # INIT-018/SPEC-003: preview-less name_near_dupe / weak overlap must NOT auto-merge (ADR D-5)
        base.reason = (
            "missing preview on one or both folders; refuse preview-less non-STRONG merge"
        )
        return base

    files_a = ", ".join(_sample_files(cand.a.path)[:25]) or "(none)"
    files_b = ", ".join(_sample_files(cand.b.path)[:25]) or "(none)"
    prompt = MERGE_VISION_PROMPT.format(
        path_a=cand.a.rel_posix,
        path_b=cand.b.rel_posix,
        files_a=files_a,
        files_b=files_b,
        signals=", ".join(signals) or "(none)",
    )

    try:
        raw = clients.gemma_vision(spark, prompt, [jpeg_a, jpeg_b])
        base.raw_vision = raw[:4000]
    except Exception as e:  # noqa: BLE001
        base.error = f"vision failed: {e}"
        base.reason = str(e)[:200]
        return base

    try:
        cleaned = clients.curator_json(
            spark,
            MERGE_CURATOR_SYSTEM,
            f"Normalize this merge decision JSON:\n\n{raw}",
        )
        data = clients.extract_json_object(cleaned)
    except Exception:
        try:
            data = clients.extract_json_object(raw)
        except Exception as e:  # noqa: BLE001
            base.error = f"json parse failed: {e}"
            base.reason = "parse_failed"
            return base

    decision = str(data.get("decision") or "keep_separate").lower().strip()
    if decision not in {"merge", "keep_separate"}:
        decision = "keep_separate"
    try:
        confidence = float(data.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    target = str(data.get("target") or "a").lower().strip()
    if target not in {"a", "b"}:
        target = "a"
    reason = str(data.get("reason") or "")[:300]

    # Post-rule: if signals are only weak overlap and vision says merge with low structural support
    if (
        decision == "merge"
        and "name_near_dupe" not in signals
        and _shared_digest_count(signals) < 1
    ):
        overlap = 0
        for s in signals:
            if s.startswith("basename_size_overlap:"):
                try:
                    overlap = int(s.split(":", 1)[1])
                except ValueError:
                    overlap = 0
        if overlap < 3:
            decision = "keep_separate"
            reason = (reason + " | forced keep_separate: weak file overlap").strip(" |")
            confidence = min(confidence, 0.5)

    base.decision = decision
    base.confidence = confidence
    base.target = target
    base.reason = reason
    base.approved_for_apply = (
        decision == "merge" and confidence >= curate.min_merge_confidence
    )
    return base


def decide_merge_pair_safe(
    cand: MergeCandidate,
    spark: SparkConfig,
    curate: CurateConfig,
    thumb_cache: Path,
) -> MergeDecision:
    try:
        return decide_merge_pair(cand, spark, curate, thumb_cache)
    except Exception as e:  # noqa: BLE001
        return MergeDecision(
            path_a=str(cand.a.path),
            path_b=str(cand.b.path),
            rel_a=cand.a.rel_posix,
            rel_b=cand.b.rel_posix,
            decision="keep_separate",
            confidence=0.0,
            target="a",
            reason=f"error: {e}",
            signals=list(cand.signals),
            approved_for_apply=False,
            error=f"{e}\n{traceback.format_exc()[-400:]}",
        )
