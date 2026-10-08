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

from . import clients, typesafe_client
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

# Entity-alignment Score: outcomes are the levels; code rounds to nearest (no fitted threshold).
MERGE_TYPESAFE_LEVELS = [
    (
        "They are two different printable products: different sculpts, poses, "
        "scales, or artists. Keep them as separate Manyfold models."
    ),
    (
        "They are closely related (same character or franchise, a possible split pack, "
        "or incomplete evidence) and a human should decide whether to merge."
    ),
    (
        "They are the same printable product: a duplicate download, renamed copy, "
        "or an obvious split of one pack that should be one Manyfold model."
    ),
]
MERGE_TYPESAFE_OUTCOME = {0: "keep_separate", 1: "curator", 2: "merge"}
MERGE_TYPESAFE_QUESTIONS = {
    "link_state": {
        "type": "score",
        "instructions": (
            "How do `folder_a` and `folder_b` relate as printable products, "
            "given `filesystem_signals`, `preview_comparison`, and `policy`?"
        ),
        "criteria": MERGE_TYPESAFE_LEVELS,
    },
    "same_printable_product": {
        "type": "noul",
        "instructions": (
            "Are `folder_a` and `folder_b` the same printable product "
            "(duplicate, rename, or split of one pack)?"
        ),
        "criteria": {
            "true": "Same downloadable pack / same sculpt files.",
            "false": "Different sculpts, poses, scales, or artists.",
        },
    },
    "character_or_franchise_only": {
        "type": "noul",
        "instructions": (
            "Do `folder_a` and `folder_b` only share a character or franchise, "
            "without being the same product?"
        ),
    },
    "keep_target": {
        "type": "choice",
        "instructions": (
            "If these folders were merged, which should remain as the Manyfold model? "
            "Prefer the better-named, more-complete pack between `folder_a` and `folder_b`."
        ),
        "criteria": {
            "a": "Keep folder_a as the surviving model.",
            "b": "Keep folder_b as the surviving model.",
        },
    },
}


def route_link_score(score_value: float) -> str:
    """Nearest Score level is the outcome; approval gates live in apply_typesafe_merge_answers."""
    level = min(max(int(score_value + 0.5), 0), 2)
    return MERGE_TYPESAFE_OUTCOME[level]


# Jev's two NOUL checks must agree with a merge before it is approved (INIT-001/SPEC-006).
SAME_PRODUCT_MIN_NOUL = 0.5
CHARACTER_ONLY_MAX_NOUL = 0.5


def _answer_float(answer: Any, key: str) -> float | None:
    """Numeric field from one TypeSafe answer; None when missing or unparsable."""
    if not isinstance(answer, dict) or answer.get(key) is None:
        return None
    try:
        return float(answer[key])
    except (TypeError, ValueError):
        return None


def _fmt(value: float | None) -> str:
    return "missing" if value is None else f"{value:.2f}"


def apply_typesafe_merge_answers(
    answers: dict[str, Any],
    *,
    min_merge_confidence: float,
) -> tuple[str, float, str, str, bool, str]:
    """
    Map TypeSafe answers to decision, confidence, target, reason, approved, outcome.

    A merge is approved only when the Score rounds to merge, link confidence is at
    least min_merge_confidence, and both NOUL checks agree. A missing answer fails
    closed. Curator ("a human should decide") is an unapproved merge plan so it
    reaches the human review log (INIT-001/SPEC-006).
    """
    link = answers.get("link_state") or {}
    score_value = _answer_float(link, "score") or 0.0
    link_conf = _answer_float(link, "confidence") or 0.0
    outcome = route_link_score(score_value)
    same_noul = _answer_float(answers.get("same_printable_product"), "noul")
    char_noul = _answer_float(answers.get("character_or_franchise_only"), "noul")
    target = str((answers.get("keep_target") or {}).get("choice") or "a").lower().strip()
    if target not in {"a", "b"}:
        target = "a"
    reason = (
        f"typesafe {outcome} score={score_value:.2f} conf={link_conf:.2f} "
        f"same_product={_fmt(same_noul)} character_only={_fmt(char_noul)}"
    )
    if outcome == "curator":
        return "merge", link_conf, target, reason + " (curator)", False, outcome
    if outcome != "merge":
        return "keep_separate", link_conf, target, reason, False, outcome

    failed: list[str] = []
    if link_conf < min_merge_confidence:
        failed.append("low confidence")
    if same_noul is None or same_noul < SAME_PRODUCT_MIN_NOUL:
        failed.append("contradicts: same_product")
    if char_noul is None or char_noul >= CHARACTER_ONLY_MAX_NOUL:
        failed.append("contradicts: character_only")
    if failed:
        return "merge", link_conf, target, f"{reason} ({'; '.join(failed)})", False, outcome
    return "merge", link_conf, target, reason, True, outcome


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
    typesafe_outcome: str | None = None
    typesafe_score: float | None = None

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


def _strong_plan_pending_review(base: MergeDecision, cand: MergeCandidate) -> MergeDecision:
    """STRONG is a plan, not permission. Jev must confirm before apply."""
    base.decision = "merge"
    base.confidence = 0.0
    base.target = "a" if len(cand.a.name) <= len(cand.b.name) else "b"
    base.reason = "STRONG structural duplicate; TypeSafe review required before apply"
    base.approved_for_apply = False
    return base


def _typesafe_state(
    cand: MergeCandidate,
    signals: list[str],
    files_a: str,
    files_b: str,
    preview_comparison: str,
    *,
    strong: bool,
) -> dict[str, Any]:
    return {
        "folder_a": {
            "path": cand.a.rel_posix,
            "name": cand.a.name,
            "files": files_a,
        },
        "folder_b": {
            "path": cand.b.rel_posix,
            "name": cand.b.name,
            "files": files_b,
        },
        "filesystem_signals": signals,
        "structural_band": "STRONG" if strong else "UNCERTAIN",
        "preview_comparison": preview_comparison,
        "policy": (
            "Merge only if they are the same printable product. "
            "Same character or franchise with different sculpts, poses, "
            "scales, or artists stays separate. "
            "A structural signal without a preview comparison is not visual confirmation."
        ),
    }


def _record_typesafe(
    base: MergeDecision,
    answers: dict[str, Any],
    signals: list[str],
    curate: CurateConfig,
    *,
    allow_approve: bool,
) -> MergeDecision:
    base.typesafe_score = _answer_float(answers.get("link_state"), "score")
    decision, confidence, target, reason, approved, outcome = apply_typesafe_merge_answers(
        answers, min_merge_confidence=curate.min_merge_confidence
    )
    base.typesafe_outcome = outcome
    if not _is_strong_structural(signals):
        decision, confidence, reason = _weak_overlap_guard(
            decision, confidence, reason, signals
        )
    if decision != "merge":
        approved = False
    if not allow_approve:
        approved = False
        if decision == "merge":
            reason = (
                reason + " | not approved without a preview comparison"
            ).strip(" |")
    base.decision = decision
    base.confidence = confidence
    base.target = target
    base.reason = reason[:300]
    base.approved_for_apply = approved and decision == "merge"
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

    # STRONG is evidence for Jev, not an automatic merge. Preview-less UNCERTAIN stays refused.
    strong = _is_strong_structural(signals)
    jpeg_a = _preview_jpeg(cand.a.path, thumb_cache, curate)
    jpeg_b = _preview_jpeg(cand.b.path, thumb_cache, curate)
    has_previews = jpeg_a is not None and jpeg_b is not None
    if strong and not has_previews and not typesafe_client.api_key_from(curate):
        decided = _strong_plan_pending_review(base, cand)
        decided.reason = "STRONG structural duplicate; missing preview; not approved"
        return decided
    if not strong and not has_previews:
        # INIT-018/SPEC-003: preview-less name_near_dupe / weak overlap must NOT auto-merge (ADR D-5)
        base.reason = (
            "missing preview on one or both folders; refuse preview-less non-STRONG merge"
        )
        return base

    files_a = ", ".join(_sample_files(cand.a.path)[:25]) or "(none)"
    files_b = ", ".join(_sample_files(cand.b.path)[:25]) or "(none)"
    raw = ""
    if has_previews:
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
            if not strong:
                base.reason = str(e)[:200]
                return base
            raw = ""

    api_key = typesafe_client.api_key_from(curate)
    if api_key:
        preview_comparison = raw[:4000] if raw else (
            "No preview comparison is available. Missing images are not evidence "
            "that the folders are the same product."
        )
        try:
            ts = typesafe_client.system_one(
                api_key=api_key,
                state=_typesafe_state(
                    cand,
                    signals,
                    files_a,
                    files_b,
                    preview_comparison,
                    strong=strong,
                ),
                questions=MERGE_TYPESAFE_QUESTIONS,
                model=curate.typesafe_model,
                base_url=curate.typesafe_base_url,
                timeout=curate.typesafe_timeout,
            )
            return _record_typesafe(
                base,
                ts.get("answers") or {},
                signals,
                curate,
                allow_approve=bool(has_previews and raw),
            )
        except Exception as e:  # noqa: BLE001
            base.error = f"typesafe failed: {type(e).__name__}: {str(e)[:180]}"
            if strong:
                decided = _strong_plan_pending_review(base, cand)
                decided.reason = "STRONG structural duplicate; TypeSafe review failed, not approved"
                return decided

    if strong and not raw:
        return _strong_plan_pending_review(base, cand)

    if not raw:
        base.reason = base.reason or "vision failed"
        return base

    try:
        cleaned = clients.curator_json(
            spark,
            MERGE_CURATOR_SYSTEM,
            f"Normalize this merge decision JSON:\n\n{raw}",
        )
        data = clients.extract_json_object(cleaned)
    except Exception as e:  # noqa: BLE001
        base.error = f"curator failed: {e}"
        base.reason = "curator_failed"
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
    decision, confidence, reason = _weak_overlap_guard(
        decision, confidence, reason, signals
    )

    base.decision = decision
    base.confidence = confidence
    base.target = target
    base.reason = reason
    base.approved_for_apply = (
        decision == "merge"
        and confidence >= curate.min_merge_confidence
        and bool(base.raw_vision)
    )
    return base


def _weak_overlap_guard(
    decision: str,
    confidence: float,
    reason: str,
    signals: list[str],
) -> tuple[str, float, str]:
    """
    Code policy: weak file overlap cannot auto-merge (ADR D-7 companion).

    Archive-overlap STRONG already has a structural signal; do not force
    keep_separate just because basename overlap is low (INIT-001/SPEC-002).
    """
    if (
        decision == "merge"
        and not _is_strong_structural(signals)
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
    return decision, confidence, reason


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
