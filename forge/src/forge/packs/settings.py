"""Pack-resolution tunables (ADR D-7). Env FORGE_PACKS_<NAME> overrides; CLI flags override env.

INIT-032/SPEC-010
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields, replace


@dataclass(frozen=True)
class PacksSettings:
    # A blob in >= commons_k packs is "commons" (bases, supports) — ignored for relatedness.
    commons_k: int = 5
    # Subset candidates come from blobs in 2..candidate_cap exact groups (bounds pair fan-out).
    candidate_cap: int = 50
    # Partial overlap ratio = shared non-commons meshes / smaller side's non-commons meshes.
    # ratio < band_low -> separate (code); band_low..band_high -> LLM; > band_high -> same (code).
    band_low: float = 0.10
    band_high: float = 1.0
    # A model root (deepest folder with datapackage.json) with more direct items (archives +
    # loose leaf folders) than this is a bundle: its units are not co-located into one pack.
    bundle_items: int = 24
    # Co-location under one non-bundle model root: "meshless" attaches only units without meshes
    # (previews, img.zip, datapackage) to the root's largest mesh unit; "all" also joins
    # mesh-bearing units (one Manyfold model = one pack; over-merges multi-release folders);
    # "off" disables it.
    colocate: str = "meshless"
    # LLM same_pack below this confidence is treated as unsure (separate + needs_review).
    min_confidence: float = 0.70
    # An LLM merge that would grow a pack beyond this many units is refused (chain guard).
    max_llm_units: int = 40
    llm_concurrency: int = 4
    # Evidence list caps (names per list, paths per side).
    evidence_names: int = 20
    evidence_paths: int = 8

    @classmethod
    def from_env(cls) -> PacksSettings:
        base = cls()
        updates = {}
        for f in fields(cls):
            raw = os.environ.get(f"FORGE_PACKS_{f.name.upper()}", "").strip()
            if raw:
                updates[f.name] = type(getattr(base, f.name))(raw)
        result = replace(base, **updates)
        result.validate()
        return result

    def validate(self) -> None:
        if self.colocate not in COLOCATE_MODES:
            raise ValueError(f"colocate must be one of {COLOCATE_MODES}, got {self.colocate!r}")
        if not 0.0 <= self.band_low <= self.band_high:
            raise ValueError("band_low must be >= 0 and <= band_high")
        if self.commons_k < 2:
            raise ValueError("commons_k must be >= 2")

    def with_overrides(self, **kwargs) -> PacksSettings:
        result = replace(self, **{k: v for k, v in kwargs.items() if v is not None})
        result.validate()
        return result


COLOCATE_MODES = ("meshless", "all", "off")
