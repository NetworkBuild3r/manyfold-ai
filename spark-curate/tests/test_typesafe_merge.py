"""TypeSafe merge routing — no live API calls."""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spark_curate.apply_merges import write_merge_plans  # noqa: E402
from spark_curate.candidates import MergeCandidate  # noqa: E402
from spark_curate.config import CurateConfig, SparkConfig  # noqa: E402
from spark_curate.decide_merge import (  # noqa: E402
    apply_typesafe_merge_answers,
    decide_merge_pair,
    route_link_score,
)
from spark_curate.merge_hitl import classify_hitl_band, should_auto_apply  # noqa: E402
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


def _answers(
    *,
    score: float = 1.9,
    confidence: float | None = 0.9,
    same: float | None = 0.95,
    char_only: float | None = 0.05,
    target: str = "a",
) -> dict:
    answers: dict = {
        "link_state": {"type": "score", "score": score, "confidence": confidence},
        "keep_target": {"type": "choice", "choice": target},
    }
    if same is not None:
        answers["same_printable_product"] = {"type": "noul", "noul": same}
    if char_only is not None:
        answers["character_or_franchise_only"] = {"type": "noul", "noul": char_only}
    return answers


class ApplyTypesafeAnswersTests(unittest.TestCase):
    """INIT-001/SPEC-006: confidence + consistency gate; curator is an unapproved plan."""

    def test_same_product_with_confidence_and_consistent_answers_approves(self) -> None:
        decision, confidence, target, reason, approved, outcome = apply_typesafe_merge_answers(
            _answers(target="b"), min_merge_confidence=0.80
        )
        self.assertEqual(decision, "merge")
        self.assertTrue(approved)
        self.assertEqual(outcome, "merge")
        self.assertEqual(target, "b")
        self.assertAlmostEqual(confidence, 0.9)
        self.assertIn("typesafe merge", reason)

    def test_each_failing_condition_blocks_approval(self) -> None:
        cases = [
            ("low confidence", _answers(confidence=0.41), "low confidence"),
            ("confidence missing", _answers(confidence=None), "low confidence"),
            ("same product low", _answers(same=0.3), "contradicts: same_product"),
            ("same product missing", _answers(same=None), "contradicts: same_product"),
            ("franchise only high", _answers(char_only=0.95), "contradicts: character_only"),
            ("franchise only at cut-off", _answers(char_only=0.5), "contradicts: character_only"),
            ("franchise only missing", _answers(char_only=None), "contradicts: character_only"),
        ]
        for name, answers, tag in cases:
            with self.subTest(name):
                decision, _conf, _target, reason, approved, outcome = apply_typesafe_merge_answers(
                    answers, min_merge_confidence=0.80
                )
                self.assertEqual(outcome, "merge")
                self.assertEqual(decision, "merge")
                self.assertFalse(approved)
                self.assertIn(tag, reason)

    def test_unparsable_noul_fails_closed(self) -> None:
        answers = _answers()
        answers["same_printable_product"]["noul"] = "very likely"
        *_rest, approved, _outcome = apply_typesafe_merge_answers(
            answers, min_merge_confidence=0.80
        )
        self.assertFalse(approved)

    def test_related_is_unapproved_merge_plan_for_curator(self) -> None:
        decision, _confidence, target, reason, approved, outcome = apply_typesafe_merge_answers(
            _answers(score=1.1, confidence=0.7, same=0.45, char_only=0.8),
            min_merge_confidence=0.80,
        )
        self.assertEqual(outcome, "curator")
        self.assertEqual(decision, "merge")
        self.assertFalse(approved)
        self.assertEqual(target, "a")
        self.assertIn("(curator)", reason)

    def test_different_products_keep_separate(self) -> None:
        decision, *_rest, approved, outcome = apply_typesafe_merge_answers(
            _answers(score=0.2), min_merge_confidence=0.80
        )
        self.assertEqual(outcome, "keep_separate")
        self.assertEqual(decision, "keep_separate")
        self.assertFalse(approved)


class CuratorPlanHitlTests(unittest.TestCase):
    """Curator plans reach the review log and are never auto-queued."""

    def _curator_decision(self, tmp: Path) -> object:
        curate = CurateConfig(typesafe_api_key="test-key", min_merge_confidence=0.80)
        ts_body = {"answers": _answers(score=1.0, confidence=0.6, same=0.5, char_only=0.4)}
        cand = _pair(tmp, ["name_near_dupe"])
        with (
            patch("spark_curate.decide_merge._preview_jpeg", return_value=b"\xff\xd8fakejpeg"),
            patch("spark_curate.decide_merge.clients.gemma_vision", return_value="similar busts"),
            patch("spark_curate.decide_merge.typesafe_client.system_one", return_value=ts_body),
        ):
            return decide_merge_pair(cand, SparkConfig(), curate, tmp / ".thumbs")

    def test_curator_plan_is_uncertain_and_never_auto_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = self._curator_decision(Path(tmp))
        self.assertEqual(d.decision, "merge")
        self.assertFalse(d.approved_for_apply)
        self.assertEqual(d.typesafe_outcome, "curator")
        self.assertEqual(classify_hitl_band(d), "UNCERTAIN")
        for mode in ("hitl_all", "hitl_uncertain", "hitl_off"):
            with self.subTest(mode):
                self.assertFalse(should_auto_apply(d, mode))

    def test_curator_plan_logged_for_review_and_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = self._curator_decision(root)
            cfg = CurateConfig(library_root=str(root), merge_hitl="hitl_off")
            log = io.StringIO()
            result = write_merge_plans(cfg, [d], do_apply=True, run_id="t", log_fh=log)
        self.assertIn("MERGE? band=UNCERTAIN", log.getvalue())
        self.assertIn("(curator)", log.getvalue())
        self.assertEqual(result["typesafe_curator"], 1)
        self.assertEqual(result["queued_for_manyfold"], 0)
        self.assertEqual(result["keep_separate"], 0)


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
