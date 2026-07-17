from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


# Default Manyfold-friendly categories (top-level under library root).
DEFAULT_CATEGORIES = [
    "Anime",
    "AnySTL",
    "B3dserk",
    "Cartoons",
    "Cosplay",
    "Cults3D",
    "D&D",
    "DC",
    "Games",
    "Movie TV",
    "Unknown",
    "WICKED",
]

# Skip these top-level names when scanning.
SKIP_TOP_LEVEL = {
    ".manyfold-organize-logs",
    ".spark-curate",
    ".inventory",
    "@eaDir",
    "#recycle",
    "System Volume Information",
}


@dataclass
class SparkConfig:
    """Endpoints on the DGX Spark inference node."""

    gemma_url: str = "http://192.168.11.161:11435/v1"
    gemma_model: str = "gemma4-uncensored"
    curator_url: str = "http://192.168.11.161:11436/v1"
    curator_model: str = "qwen2.5-1.5b-instruct"
    nudenet_url: str = "http://192.168.11.161:8090"
    embed_url: str = "http://192.168.11.161:8000/v1"
    embed_model: str = "BAAI/bge-m3"
    # Request timeouts (seconds)
    vision_timeout: float = 180.0
    curator_timeout: float = 60.0
    nudenet_timeout: float = 30.0
    max_tokens_vision: int = 1200
    max_tokens_curator: int = 800
    temperature: float = 0.15


@dataclass
class CurateConfig:
    """Library paths and policy."""

    # In Docker the library is always mounted at /library
    library_root: str = "/library"
    # State + logs always under library (or override)
    work_dir: str = ""  # default: <library>/.spark-curate
    categories: list[str] = field(default_factory=lambda: list(DEFAULT_CATEGORIES))
    # Auto-apply moves when confidence >= this (no human). Raise for safer.
    min_confidence: float = 0.55
    # Only rearrange; never delete sources or empty parents aggressively
    never_delete: bool = True
    # Parallel vision workers (keep low on unified memory)
    workers: int = 2
    # Limit folders for a pilot run (0 = all)
    limit: int = 0
    # Only process these top-level categories (empty = all)
    only_categories: list[str] = field(default_factory=list)
    # Skip models that already look well-placed (optional speed-up)
    skip_if_has_preview_and_known_category: bool = False
    # NudeNet: mark sensitive when max score >= this
    nudenet_sensitive_threshold: float = 0.6
    # Max image edge for API (resize before base64)
    max_image_edge: int = 1024
    jpeg_quality: int = 85

    def resolved_work_dir(self) -> Path:
        if self.work_dir:
            return Path(self.work_dir)
        return Path(self.library_root) / ".spark-curate"


def load_config(path: str | Path | None) -> tuple[SparkConfig, CurateConfig]:
    spark = SparkConfig()
    curate = CurateConfig()
    if not path:
        return spark, curate
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Config not found: {p}")
    raw: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    if "spark" in raw:
        for k, v in raw["spark"].items():
            if hasattr(spark, k):
                setattr(spark, k, v)
    if "curate" in raw:
        for k, v in raw["curate"].items():
            if hasattr(curate, k):
                setattr(curate, k, v)
    # Flat keys also allowed
    for k, v in raw.items():
        if k in ("spark", "curate"):
            continue
        if hasattr(spark, k):
            setattr(spark, k, v)
        elif hasattr(curate, k):
            setattr(curate, k, v)
    return spark, curate


def save_example_config(path: Path) -> None:
    example = {
        "spark": asdict(SparkConfig()),
        "curate": asdict(CurateConfig()),
    }
    path.write_text(json.dumps(example, indent=2), encoding="utf-8")
