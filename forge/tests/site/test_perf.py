"""50k-pair render budget. INIT-032/SPEC-014."""

from __future__ import annotations

import json
import time
from pathlib import Path

from forge.site.render import render_site

PAIRS = 50_000
RENDER_BUDGET_S = 30
INITIAL_BUDGET = 1_000_000


def _synth_pair(i: int) -> dict:
    return {
        "pack_a": f"Games/pack-{i % 200:03d}.zip",
        "pack_b": f"Misc/pack-{(i % 200) + 200:03d}.zip",
        "kind_a": "archive",
        "kind_b": "archive",
        "meshes_a": 10,
        "meshes_b": 10,
        "bytes_a": 1000,
        "bytes_b": 1000,
        "shared_meshes": 3,
        "shared_bytes": 300,
        "containment_count": 0.3,
        "containment_bytes": 0.3,
        "overlap_a": 0.3,
        "overlap_b": 0.3,
        "overlap_a_bytes": 0.3,
        "overlap_b_bytes": 0.3,
        "archives_differ": True,
        "archive_sha_a": "aa" * 32,
        "archive_sha_b": "bb" * 32,
        "shared": [
            {"sha256": f"{i:064x}", "size": 100, "name": f"mesh-{i}.stl"},
        ],
    }


def test_fifty_thousand_pairs_render_and_initial_payload(tmp_path: Path) -> None:
    src = tmp_path / "in"
    src.mkdir()
    (src / "inventory.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "report": "inventory",
                "generated_at": "2026-10-03T00:00:00Z",
                "have": {
                    "unique_meshes": 1,
                    "unique_mesh_bytes": 100,
                    "mesh_occurrences": 2,
                    "duplicate_ratio": 0.5,
                },
                "archives_vs_loose": [],
                "failures": [],
                "failed_containers": [],
            }
        ),
        encoding="utf-8",
    )
    doc = {
        "schema_version": 1,
        "report": "duplicates",
        "generated_at": "2026-10-03T00:00:00Z",
        "have": {"unique_meshes": 1, "reclaimable_bytes": 100, "duplicate_ratio": 0.5},
        "pairs": [_synth_pair(i) for i in range(PAIRS)],
    }
    (src / "duplicates.json").write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    out = tmp_path / "site"
    t0 = time.perf_counter()
    render_site(src, out)
    elapsed = time.perf_counter() - t0
    assert elapsed < RENDER_BUDGET_S, f"render took {elapsed:.2f}s"
    initial = 0
    for rel in (
        "index.html",
        "inventory.html",
        "duplicates.html",
        "assets/site.css",
        "assets/site.js",
        "data/pairs/meta.json",
        "data/pairs/c0000.json",
    ):
        initial += (out / rel).stat().st_size
    assert initial < INITIAL_BUDGET, f"initial payload {initial} bytes"
    meta = json.loads((out / "data/pairs/meta.json").read_text(encoding="utf-8"))
    assert meta["pairCount"] == PAIRS
    assert meta["chunkCount"] == 200
