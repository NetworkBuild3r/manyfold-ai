# Unit tests for decide_merge_pair banding (INIT-018/SPEC-003).
# No Spark / Gemma calls — preview path is mocked.
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spark_curate.candidates import MergeCandidate  # noqa: E402
from spark_curate.config import CurateConfig, SparkConfig  # noqa: E402
from spark_curate.decide_merge import (  # noqa: E402
    _is_strong_structural,
    decide_merge_pair,
)
from spark_curate.walk import ModelFolder  # noqa: E402


def _pair(
    tmp: Path,
    *,
    name_a: str = "Pack",
    name_b: str = "Pack (2)",
    signals: list[str],
) -> MergeCandidate:
    cat = "DC"
    a = tmp / cat / name_a
    b = tmp / cat / name_b
    a.mkdir(parents=True, exist_ok=True)
    b.mkdir(parents=True, exist_ok=True)
    (a / "model.stl").write_bytes(b"a")
    (b / "model.stl").write_bytes(b"b")
    return MergeCandidate(
        a=ModelFolder(path=a, category=cat, name=name_a),
        b=ModelFolder(path=b, category=cat, name=name_b),
        signals=list(signals),
    )


class StrongBandHelpersTests(unittest.TestCase):
    def test_name_near_dupe_is_not_strong(self) -> None:
        self.assertFalse(_is_strong_structural(["name_near_dupe"]))

    def test_shared_digest_is_strong(self) -> None:
        self.assertTrue(_is_strong_structural(["shared_digest"]))

    def test_archive_overlap_below_t_is_not_strong(self) -> None:
        self.assertFalse(
            _is_strong_structural(
                ["shared_archive_member", "archive_member_overlap:2", "name_near_dupe"]
            )
        )

    def test_archive_overlap_at_t_is_strong(self) -> None:
        self.assertTrue(
            _is_strong_structural(["shared_archive_member", "archive_member_overlap:3"])
        )


class DecideMergeLandmineTests(unittest.TestCase):
    """ADR D-5: preview-less name-only / weak overlap must keep_separate."""

    def setUp(self) -> None:
        self.spark = SparkConfig()
        self.curate = CurateConfig(min_merge_confidence=0.80)

    def test_ac1_previewless_name_near_dupe_keep_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cand = _pair(Path(tmp), signals=["name_near_dupe"])
            with patch(
                "spark_curate.decide_merge._preview_jpeg",
                return_value=None,
            ):
                d = decide_merge_pair(cand, self.spark, self.curate, Path(tmp) / ".thumbs")
            self.assertEqual(d.decision, "keep_separate")
            self.assertFalse(d.approved_for_apply)
            self.assertNotAlmostEqual(d.confidence, 0.82)
            self.assertIn("preview-less", d.reason)

    def test_ac2_previewless_weak_overlap_keep_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cand = _pair(
                Path(tmp),
                signals=["basename_size_overlap:1", "archive_member_overlap:1"],
            )
            with patch(
                "spark_curate.decide_merge._preview_jpeg",
                return_value=None,
            ):
                d = decide_merge_pair(cand, self.spark, self.curate, Path(tmp) / ".thumbs")
            self.assertEqual(d.decision, "keep_separate")
            self.assertFalse(d.approved_for_apply)
            self.assertIn("preview-less", d.reason)

    def test_ac3_franchise_only_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # No structural signals — franchise/character equality alone
            cand = _pair(
                Path(tmp),
                name_a="Batman Bust",
                name_b="Batman Full Body",
                signals=[],
            )
            d = decide_merge_pair(cand, self.spark, self.curate, Path(tmp) / ".thumbs")
            self.assertEqual(d.decision, "keep_separate")
            self.assertFalse(d.approved_for_apply)
            self.assertIn("franchise-only", d.reason)

    def test_strong_shared_digest_previewless_still_merges(self) -> None:
        """aud-1: multi-file shared_digest may remain STRONG without Gemma."""
        with tempfile.TemporaryDirectory() as tmp:
            cand = _pair(Path(tmp), signals=["shared_digest", "name_near_dupe"])
            with patch(
                "spark_curate.decide_merge._preview_jpeg",
                return_value=None,
            ):
                d = decide_merge_pair(cand, self.spark, self.curate, Path(tmp) / ".thumbs")
            self.assertEqual(d.decision, "merge")
            self.assertGreaterEqual(d.confidence, 0.80)
            self.assertTrue(d.approved_for_apply)
            self.assertIn("STRONG", d.reason)

    def test_strong_archive_overlap_skips_gemma_with_previews(self) -> None:
        """SPEC-005 hook: ≥T mesh overlaps → STRONG, skip Gemma even with JPEGs."""
        with tempfile.TemporaryDirectory() as tmp:
            cand = _pair(
                Path(tmp),
                signals=["shared_archive_member", "archive_member_overlap:3"],
            )
            with patch(
                "spark_curate.decide_merge._preview_jpeg",
                return_value=b"\xff\xd8fakejpeg",
            ), patch("spark_curate.decide_merge.clients.gemma_vision") as gemma:
                d = decide_merge_pair(cand, self.spark, self.curate, Path(tmp) / ".thumbs")
            gemma.assert_not_called()
            self.assertEqual(d.decision, "merge")
            self.assertTrue(d.approved_for_apply)


if __name__ == "__main__":
    unittest.main()
