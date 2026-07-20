# Lightweight unit checks for merge candidate heuristics (no Spark).
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spark_curate.candidates import (  # noqa: E402
    FolderFingerprint,
    MergeCandidate,
    build_merge_candidates,
    normalize_model_slug,
)
from spark_curate.config import CurateConfig  # noqa: E402
from spark_curate.decide_merge import MergeDecision  # noqa: E402
from spark_curate.walk import ModelFolder  # noqa: E402


class NormalizeSlugTests(unittest.TestCase):
    def test_strips_numeric_suffix(self) -> None:
        self.assertEqual(normalize_model_slug("Batman Pack (2)"), normalize_model_slug("Batman Pack"))

    def test_different_sculpts_differ(self) -> None:
        self.assertNotEqual(
            normalize_model_slug("Batman Bust"),
            normalize_model_slug("Batman Full Body"),
        )


class CandidatePolicyTests(unittest.TestCase):
    def test_two_different_batmans_not_paired_without_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "DC" / "Batman Bust"
            b = root / "DC" / "Batman Full Body"
            a.mkdir(parents=True)
            b.mkdir(parents=True)
            (a / "bust.stl").write_bytes(b"aaa")
            (b / "full.stl").write_bytes(b"bbb")
            cfg = CurateConfig(library_root=str(root), only_categories=["DC"], max_merge_pairs=50)
            pairs = build_merge_candidates(cfg)
            self.assertEqual(pairs, [])

    def test_near_dupe_name_is_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "DC" / "Batman Pack"
            b = root / "DC" / "Batman Pack (2)"
            a.mkdir(parents=True)
            b.mkdir(parents=True)
            (a / "model.stl").write_bytes(b"same")
            (b / "model.stl").write_bytes(b"same")
            cfg = CurateConfig(library_root=str(root), only_categories=["DC"], max_merge_pairs=50)
            pairs = build_merge_candidates(cfg)
            self.assertEqual(len(pairs), 1)
            self.assertIn("name_near_dupe", pairs[0].signals)


class MergeDecisionGateTests(unittest.TestCase):
    def test_approved_requires_threshold(self) -> None:
        d = MergeDecision(
            path_a="/x/a",
            path_b="/x/b",
            rel_a="DC/a",
            rel_b="DC/b",
            decision="merge",
            confidence=0.79,
            target="a",
            reason="close",
            signals=["name_near_dupe"],
            approved_for_apply=False,
        )
        self.assertFalse(d.approved_for_apply)
        d2 = MergeDecision(
            path_a="/x/a",
            path_b="/x/b",
            rel_a="DC/a",
            rel_b="DC/b",
            decision="merge",
            confidence=0.80,
            target="a",
            reason="sure",
            signals=["name_near_dupe"],
            approved_for_apply=True,
        )
        self.assertTrue(d2.approved_for_apply)


if __name__ == "__main__":
    unittest.main()
