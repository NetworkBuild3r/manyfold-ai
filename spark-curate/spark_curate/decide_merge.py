"""Vision-based merge decision for a candidate pair."""
from __future__ import annotations

import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import clients
from .candidates import MergeCandidate
from .config import CurateConfig, SparkConfig
from .decide import _sample_files
from .preview import best_image, load_image_as_jpeg_bytes, try_extract_preview_from_zip


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
    structural = any(
        s == "name_near_dupe" or s == "shared_digest" or s.startswith("basename_size_overlap")
        for s in signals
    )
    if not structural:
        base.reason = "no structural duplicate signal; refuse franchise-only merge"
        return base

    jpeg_a = _preview_jpeg(cand.a.path, thumb_cache, curate)
    jpeg_b = _preview_jpeg(cand.b.path, thumb_cache, curate)
    if jpeg_a is None or jpeg_b is None:
        # Without both previews, only auto-merge on very strong digest/name+(2) signals
        if "shared_digest" in signals or "name_near_dupe" in signals:
            base.decision = "merge"
            base.confidence = 0.85 if "shared_digest" in signals else 0.82
            base.target = "a" if len(cand.a.name) <= len(cand.b.name) else "b"
            base.reason = "structural duplicate without both previews"
            base.approved_for_apply = base.confidence >= curate.min_merge_confidence
            return base
        base.reason = "missing preview on one or both folders"
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
    if decision == "merge" and "name_near_dupe" not in signals and "shared_digest" not in signals:
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
