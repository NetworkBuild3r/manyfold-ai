from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from . import clients
from .config import CurateConfig, SparkConfig
from .preview import best_image, load_image_as_jpeg_bytes, try_extract_preview_from_zip
from .walk import ModelFolder


VISION_PROMPT = """You curate a 3D-print digital library for Manyfold software.
Manyfold needs: one folder = one model, under Category/ModelName/, with a preview image when possible.

ALLOWED CATEGORIES (pick exactly one):
{categories}

Current location:
- category: {category}
- folder_name: {name}
- relative: {rel}
- files (sample): {files}

Look at the product/preview image. Return ONLY a single JSON object (no markdown) with keys:
{{
  "suggested_name": "clean human model title, max 80 chars",
  "category": "one of the allowed categories",
  "tags": ["lowercase", "short", "tags"],
  "has_usable_preview": true,
  "content_type": "character|prop|terrain|mechanical|cosplay_armor|miniature|other",
  "is_junk": false,
  "junk_reason": null,
  "confidence": 0.0,
  "action": "keep|rename|move|skip",
  "notes": "one short sentence"
}}

Rules:
- category MUST be one of the allowed list (use Unknown if unsure).
- suggested_name: no timestamps like -20221108T063302Z-001, no "Copy of", no illegal path chars.
- action=keep if category and name are already good.
- action=rename if only the folder name should change (same category).
- action=move if category should change (and name may change).
- action=skip only if this is clearly not a 3D model pack (e.g. pure docs).
- confidence is 0..1.
- tags: 0-8 items, useful for search.
"""


CURATOR_SYSTEM = """You normalize JSON for a filesystem reorganizer.
Output ONLY valid JSON (no markdown). Fix keys to the schema. category MUST be one of: {categories}.
Schema:
{{
  "suggested_name": string,
  "category": string,
  "tags": string[],
  "has_usable_preview": boolean,
  "content_type": string,
  "is_junk": boolean,
  "junk_reason": string|null,
  "confidence": number,
  "action": "keep"|"rename"|"move"|"skip",
  "notes": string
}}
If input is garbage, set action=skip, confidence=0, category=Unknown.
"""


@dataclass
class Decision:
    source_path: str
    current_category: str
    current_name: str
    suggested_name: str
    category: str
    tags: list[str]
    has_usable_preview: bool
    content_type: str
    is_junk: bool
    junk_reason: str | None
    confidence: float
    action: str
    notes: str
    sensitive: bool
    nudenet: dict[str, Any]
    thumb_path: str | None
    error: str | None = None
    raw_vision: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sample_files(folder: Path, limit: int = 40) -> list[str]:
    names: list[str] = []
    try:
        for p in sorted(folder.rglob("*")):
            if not p.is_file():
                continue
            if any(part.startswith(".") for part in p.relative_to(folder).parts):
                continue
            try:
                rel = str(p.relative_to(folder)).replace("\\", "/")
            except ValueError:
                continue
            names.append(rel)
            if len(names) >= limit:
                break
    except OSError:
        pass
    return names


def _safe_name(name: str) -> str:
    if not name or not str(name).strip():
        return "unnamed-model"
    n = str(name).strip()
    for prefix in ("Copy of ", "copy of "):
        if n.startswith(prefix):
            n = n[len(prefix) :]
    # strip common timestamp suffixes
    import re

    n = re.sub(r"-?\d{8}T\d{6}Z?(-\d+)?$", "", n)
    n = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", n)
    n = re.sub(r"\s+", " ", n).strip(" .")
    if len(n) > 100:
        n = n[:100].strip()
    return n or "unnamed-model"


def _normalize_category(cat: str, allowed: list[str]) -> str:
    if not cat:
        return "Unknown"
    for a in allowed:
        if a.lower() == cat.strip().lower():
            return a
    # light aliases
    aliases = {
        "dnd": "D&D",
        "d and d": "D&D",
        "movies": "Movie TV",
        "movie": "Movie TV",
        "tv": "Movie TV",
        "marvel": "Games",
        "cartoons": "Cartoons",
        "cartoon": "Cartoons",
    }
    key = cat.strip().lower()
    if key in aliases:
        return aliases[key]
    return "Unknown"


def _nudenet_sensitive(result: dict[str, Any], threshold: float) -> tuple[bool, dict[str, Any]]:
    detections = result.get("detections") or result.get("predictions") or result.get("result") or []
    if not isinstance(detections, list):
        detections = []
    max_score = 0.0
    classes: list[str] = []
    # High-signal exposure-ish labels (NudeNet class names vary by version)
    hot = {
        "FEMALE_BREAST_EXPOSED",
        "FEMALE_GENITALIA_EXPOSED",
        "MALE_GENITALIA_EXPOSED",
        "BUTTOCKS_EXPOSED",
        "ANUS_EXPOSED",
        "FEMALE_BREAST_COVERED",  # optional softer
    }
    for d in detections:
        if not isinstance(d, dict):
            continue
        label = str(d.get("class") or d.get("label") or d.get("name") or "").upper()
        score = float(d.get("score") or d.get("confidence") or 0)
        max_score = max(max_score, score)
        if label:
            classes.append(label)
    # Prefer class-based sensitive if hot labels with decent score
    sensitive = False
    for d in detections:
        if not isinstance(d, dict):
            continue
        label = str(d.get("class") or d.get("label") or d.get("name") or "").upper()
        score = float(d.get("score") or d.get("confidence") or 0)
        if label in hot and score >= threshold:
            sensitive = True
            break
    if not sensitive and max_score >= max(threshold, 0.85):
        # very high generic score without class map
        sensitive = any("EXPOSED" in c for c in classes)
    summary = {
        "count": len(detections),
        "max_score": max_score,
        "top_classes": classes[:12],
    }
    return sensitive, summary


def decide_one(
    folder: ModelFolder,
    spark: SparkConfig,
    curate: CurateConfig,
    thumb_cache: Path,
) -> Decision:
    thumb = best_image(folder.path)
    if thumb is None:
        thumb = try_extract_preview_from_zip(folder.path, thumb_cache)

    files = _sample_files(folder.path)
    base = Decision(
        source_path=str(folder.path),
        current_category=folder.category,
        current_name=folder.name,
        suggested_name=folder.name,
        category=folder.category,
        tags=[],
        has_usable_preview=thumb is not None,
        content_type="other",
        is_junk=False,
        junk_reason=None,
        confidence=0.0,
        action="keep",
        notes="",
        sensitive=False,
        nudenet={},
        thumb_path=str(thumb) if thumb else None,
    )

    if thumb is None:
        base.action = "skip"
        base.notes = "No preview image available; left in place (no delete)."
        base.confidence = 0.0
        return base

    try:
        jpeg = load_image_as_jpeg_bytes(thumb, curate.max_image_edge, curate.jpeg_quality)
    except OSError as e:
        base.error = f"read image failed: {e}"
        base.action = "skip"
        return base

    # NudeNet (optional — failures do not block vision)
    try:
        nn = clients.nudenet_detect_bytes(spark, jpeg, filename=thumb.name)
        sensitive, summary = _nudenet_sensitive(nn, curate.nudenet_sensitive_threshold)
        base.sensitive = sensitive
        base.nudenet = summary
    except Exception as e:  # noqa: BLE001
        base.nudenet = {"error": str(e)[:200]}

    cats = ", ".join(curate.categories)
    prompt = VISION_PROMPT.format(
        categories=cats,
        category=folder.category,
        name=folder.name,
        rel=folder.rel_posix,
        files=", ".join(files[:30]) or "(none listed)",
    )

    try:
        raw = clients.gemma_vision(spark, prompt, jpeg)
        base.raw_vision = raw[:4000]
    except Exception as e:  # noqa: BLE001
        base.error = f"vision failed: {e}"
        base.action = "skip"
        return base

    # Curator normalize
    try:
        cleaned = clients.curator_json(
            spark,
            CURATOR_SYSTEM.format(categories=cats),
            f"Normalize this model output to schema JSON:\n\n{raw}",
        )
        data = clients.extract_json_object(cleaned)
    except Exception:
        try:
            data = clients.extract_json_object(raw)
        except Exception as e:  # noqa: BLE001
            base.error = f"json parse failed: {e}"
            base.action = "skip"
            base.confidence = 0.0
            return base

    base.suggested_name = _safe_name(str(data.get("suggested_name") or folder.name))
    base.category = _normalize_category(str(data.get("category") or "Unknown"), curate.categories)
    tags = data.get("tags") or []
    if isinstance(tags, list):
        base.tags = [str(t).strip().lower() for t in tags if str(t).strip()][:8]
    base.has_usable_preview = bool(data.get("has_usable_preview", True))
    base.content_type = str(data.get("content_type") or "other")
    base.is_junk = bool(data.get("is_junk", False))
    base.junk_reason = data.get("junk_reason")
    try:
        base.confidence = float(data.get("confidence") or 0)
    except (TypeError, ValueError):
        base.confidence = 0.0
    action = str(data.get("action") or "keep").lower().strip()
    if action not in {"keep", "rename", "move", "skip"}:
        action = "keep"
    base.action = action
    base.notes = str(data.get("notes") or "")[:300]

    # Derive action from paths if model said keep but category differs
    if base.action == "keep":
        if base.category != folder.category:
            base.action = "move"
        elif base.suggested_name != folder.name:
            base.action = "rename"

    if base.is_junk:
        # Never delete: keep in place, only tag via notes
        base.action = "keep"
        base.notes = (base.notes + " | flagged junk but left in place").strip(" |")

    return base
