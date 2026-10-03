"""Read existing spark-curate metadata (datapackage.json, .spark-curate-meta.json) — read-only.

Files are opened O_RDONLY | O_NOFOLLOW under FORGE_SOURCE_ROOT, capped at 1 MiB, and only ever
read. Missing root / file / bad JSON yields an empty record, never an error.

INIT-032/SPEC-011
"""

from __future__ import annotations

import json
import os
import posixpath
from dataclasses import dataclass, field
from pathlib import Path

MAX_BYTES = 1 << 20
DATAPACKAGE = "datapackage.json"
SPARK_META = ".spark-curate-meta.json"


@dataclass
class ModelMeta:
    title: str | None = None
    keywords: list[str] = field(default_factory=list)
    creator: str | None = None
    caption: str | None = None

    def as_evidence(self) -> dict:
        return {
            "title": self.title,
            "keywords": self.keywords[:20],
            "creator": self.creator,
            "caption": (self.caption or "")[:300] or None,
        }


def _read_json(root: Path, rel: str) -> dict | None:
    rel = rel.lstrip("/")
    if ".." in rel.split("/"):
        return None
    full = root / rel
    try:
        fd = os.open(full, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        return None
    try:
        with os.fdopen(fd, "rb") as fh:
            data = fh.read(MAX_BYTES + 1)
    except OSError:
        return None
    if len(data) > MAX_BYTES:
        return None
    try:
        obj = json.loads(data.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _str(v) -> str | None:
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def parse_meta(dp: dict | None, spark: dict | None) -> ModelMeta:
    meta = ModelMeta()
    if dp:
        meta.title = _str(dp.get("title"))
        meta.caption = _str(dp.get("caption")) or _str(dp.get("description"))
        kws = dp.get("keywords")
        if isinstance(kws, list):
            meta.keywords = [k.strip() for k in kws if isinstance(k, str) and k.strip()]
        for c in dp.get("contributors") or []:
            if isinstance(c, dict) and "creator" in (c.get("roles") or []):
                meta.creator = _str(c.get("title"))
                if meta.creator:
                    break
    if spark:
        if not meta.creator:
            meta.creator = _str(spark.get("creator"))
        kws = spark.get("keywords")
        if not meta.keywords and isinstance(kws, list):
            meta.keywords = [k.strip() for k in kws if isinstance(k, str) and k.strip()]
    return meta


class MetaReader:
    def __init__(self, source_root: str | None) -> None:
        self.root = Path(source_root) if source_root else None
        self._cache: dict[str, ModelMeta] = {}
        self.read = 0

    @property
    def enabled(self) -> bool:
        return self.root is not None and self.root.is_dir()

    def for_root(self, model_root: str | None) -> ModelMeta:
        if model_root is None or not self.enabled:
            return ModelMeta()
        if model_root not in self._cache:
            assert self.root is not None
            dp = _read_json(self.root, posixpath.join(model_root, DATAPACKAGE))
            spark = _read_json(self.root, posixpath.join(model_root, SPARK_META))
            self.read += 1
            self._cache[model_root] = parse_meta(dp, spark)
        return self._cache[model_root]
