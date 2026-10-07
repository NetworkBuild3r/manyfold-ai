"""TypeSafe merge routing — no live API calls."""
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
    apply_typesafe_merge_answers,
    decide_merge_pair,
    route_link_score,
)
from spark_curate.walk import ModelFolder  # noqa: E402


def _pair(tmp: Path, signals: list[str]) -> MergeCandidate:
    cat = "DC"
    a = tmp / cat / "Pack"
    b = tmp / cat / "Pack (2)"
    a.mkdir(parents=True, exist_ok=True)
    b.mkdir(parents=True, exist_ok=True)
    (a / "model.stl").write_bytes(b"a")
    (b / "model.stl").write_bytes(b"b")
    return MergeCandidate(
        a=ModelFolder(path=a, category=cat, name="Pack"),
        b=ModelFolder(path=b, category=cat, name="Pack (2)"),
        signals=list(signals),
    )


class RouteLinkScoreTests(unittest.TestCase):
    def test_rounds_to_nearest_level(self) -> None:
        self.assertEqual(route_link_score(0.2), "keep_separate")
        self.assertEqual(route_link_score(0.6), "curator")
        self.assertEqual(route_link_score(1.4), "curator")
        self.assertEqual(route_link_score(1.6), "merge")
        self.assertEqual(route_link_score(1.94), "merge")


class ApplyTypesafeAnswersTests(unittest.TestCase):
    def test_same_product_merges_without_extra_threshold(self) -> None:
        answers = {
            "link_state": {
                "type": "score",
                "score": 1.91,
                "confidence": 0.41,
            },
            "same_printable_product": {"type": "noul", "noul": 0.96},
            "character_or_franchise_only": {"type": "noul", "noul": 0.04},
            "keep_target": {"type": "choice", "choice": "b"},
        }
        decision, confidence, target, reason, approved = apply_typesafe_merge_answers(
            answers, min_merge_confidence=0.80
        )
        self.assertEqual(decision, "merge")
        self.assertTrue(approved)
        self.assertEqual(target, "b")
        self.assertIn("typesafe merge", reason)

    def test_related_goes_to_curator_not_merge(self) -> None:
        answers = {
            "link_state": {"type": "score", "score": 1.1, "confidence": 0.7},
            "same_printable_product": {"type": "noul", "noul": 0.45},
            "character_or_franchise_only": {"type": "noul", "noul": 0.8},
            "keep_target": {"type": "choice", "choice": "a"},
        }
        decision, _confidence, target, reason, approved = apply_typesafe_merge_answers(
            answers, min_merge_confidence=0.80
        )
        self.assertEqual(decision, "keep_separate")
        self.assertFalse(approved)
        self.assertEqual(target, "a")
        self.assertIn("curator", reason)


class DecideMergeTypesafePathTests(unittest.TestCase):
    def test_uncertain_with_previews_uses_typesafe_not_qwen(self) -> None:
        spark = SparkConfig()
        curate = CurateConfig(typesafe_api_key="test-key", min_merge_confidence=0.80)
        ts_body = {
            "answers": {
                "link_state": {"type": "score", "score": 1.88, "confidence": 0.9},
                "same_printable_product": {"type": "noul", "noul": 0.93},
                "character_or_franchise_only": {"type": "noul", "noul": 0.05},
                "keep_target": {"type": "choice", "choice": "a"},
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            cand = _pair(Path(tmp), ["name_near_dupe"])
            with (
                patch(
                    "spark_curate.decide_merge._preview_jpeg",
                    return_value=b"\xff\xd8fakejpeg",
                ),
                patch(
                    "spark_curate.decide_merge.clients.gemma_vision",
                    return_value='{"notes": "same pack, renamed"}',
                ) as gemma,
                patch(
                    "spark_curate.decide_merge.typesafe_client.system_one",
                    return_value=ts_body,
                ) as ts,
                patch("spark_curate.decide_merge.clients.curator_json") as qwen,
            ):
                d = decide_merge_pair(cand, spark, curate, Path(tmp) / ".thumbs")
            gemma.assert_called_once()
            ts.assert_called_once()
            qwen.assert_not_called()
            self.assertEqual(d.decision, "merge")
            self.assertTrue(d.approved_for_apply)
            self.assertEqual(d.typesafe_outcome, "merge")

    def test_strong_with_previews_approves_only_when_jev_says_merge(self) -> None:
        spark = SparkConfig()
        curate = CurateConfig(typesafe_api_key="test-key", min_merge_confidence=0.80)
        ts_body = {
            "answers": {
                "link_state": {"type": "score", "score": 1.9, "confidence": 0.88},
                "same_printable_product": {"type": "noul", "noul": 0.95},
                "character_or_franchise_only": {"type": "noul", "noul": 0.02},
                "keep_target": {"type": "choice", "choice": "a"},
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            cand = _pair(Path(tmp), ["shared_digest:2", "name_near_dupe"])
            with (
                patch(
                    "spark_curate.decide_merge._preview_jpeg",
                    return_value=b"\xff\xd8fakejpeg",
                ),
                patch(
                    "spark_curate.decide_merge.clients.gemma_vision",
                    return_value="both previews show the same bust",
                ) as gemma,
                patch(
                    "spark_curate.decide_merge.typesafe_client.system_one",
                    return_value=ts_body,
                ) as ts,
            ):
                d = decide_merge_pair(cand, spark, curate, Path(tmp) / ".thumbs")
            gemma.assert_called_once()
            ts.assert_called_once()
            state = ts.call_args.kwargs["state"]
            self.assertEqual(state["structural_band"], "STRONG")
            self.assertIn("same bust", state["preview_comparison"])
            self.assertEqual(d.decision, "merge")
            self.assertTrue(d.approved_for_apply)

    def test_strong_without_previews_is_not_approved_even_if_jev_says_merge(self) -> None:
        spark = SparkConfig()
        curate = CurateConfig(typesafe_api_key="test-key")
        ts_body = {
            "answers": {
                "link_state": {"type": "score", "score": 1.9, "confidence": 0.9},
                "same_printable_product": {"type": "noul", "noul": 0.9},
                "character_or_franchise_only": {"type": "noul", "noul": 0.1},
                "keep_target": {"type": "choice", "choice": "a"},
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            cand = _pair(Path(tmp), ["archive_member_overlap:3", "shared_archive_member"])
            with (
                patch("spark_curate.decide_merge._preview_jpeg", return_value=None),
                patch("spark_curate.decide_merge.clients.gemma_vision") as gemma,
                patch(
                    "spark_curate.decide_merge.typesafe_client.system_one",
                    return_value=ts_body,
                ),
            ):
                d = decide_merge_pair(cand, spark, curate, Path(tmp) / ".thumbs")
            gemma.assert_not_called()
            self.assertEqual(d.decision, "merge")
            self.assertFalse(d.approved_for_apply)
            self.assertIn("not approved without a preview comparison", d.reason)


if __name__ == "__main__":
    unittest.main()
