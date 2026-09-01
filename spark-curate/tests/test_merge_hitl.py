# Unit tests for graduated MERGE_HITL apply modes (INIT-018/SPEC-006).
# Mode matrix × bands; no Spark / Gemma / NFS.
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spark_curate.apply_merges import write_merge_plans  # noqa: E402
from spark_curate.config import CurateConfig, load_config  # noqa: E402
from spark_curate.decide_merge import MergeDecision  # noqa: E402
from spark_curate.merge_hitl import (  # noqa: E402
    DEFAULT_MERGE_HITL,
    InvalidMergeHitlError,
    classify_hitl_band,
    parse_merge_hitl,
    should_auto_apply,
)


def _decision(
    *,
    decision: str = "merge",
    confidence: float = 0.85,
    approved: bool = True,
    signals: list[str] | None = None,
    reason: str = "test",
) -> MergeDecision:
    return MergeDecision(
        path_a="/library/DC/A",
        path_b="/library/DC/B",
        rel_a="DC/A",
        rel_b="DC/B",
        decision=decision,
        confidence=confidence,
        target="a",
        reason=reason,
        signals=list(signals or []),
        approved_for_apply=approved,
    )


def _strong(**kwargs: object) -> MergeDecision:
    # Multi-file digest (N≥2) — SEC-018-02 / ADR D-4
    return _decision(signals=["shared_digest:2"], **kwargs)  # type: ignore[arg-type]


def _uncertain(**kwargs: object) -> MergeDecision:
    return _decision(signals=["name_near_dupe"], **kwargs)  # type: ignore[arg-type]


def _refuse(**kwargs: object) -> MergeDecision:
    return _decision(
        decision="keep_separate",
        approved=False,
        confidence=0.0,
        signals=["name_near_dupe"],
        reason="missing preview",
        **kwargs,  # type: ignore[arg-type]
    )


class ParseMergeHitlTests(unittest.TestCase):
    def test_default_is_hitl_all(self) -> None:
        self.assertEqual(parse_merge_hitl(None), "hitl_all")
        self.assertEqual(parse_merge_hitl(""), "hitl_all")
        self.assertEqual(parse_merge_hitl("  "), "hitl_all")
        self.assertEqual(DEFAULT_MERGE_HITL, "hitl_all")

    def test_valid_modes(self) -> None:
        for mode in ("hitl_all", "hitl_uncertain", "hitl_off"):
            self.assertEqual(parse_merge_hitl(mode), mode)

    def test_invalid_fails_loud_never_coerce_to_hitl_off(self) -> None:
        with self.assertRaises(InvalidMergeHitlError) as ctx:
            parse_merge_hitl("hitl_maybe")
        self.assertIn("hitl_off", str(ctx.exception))
        with self.assertRaises(InvalidMergeHitlError):
            parse_merge_hitl("off")
        with self.assertRaises(InvalidMergeHitlError):
            parse_merge_hitl("true")


class ClassifyBandTests(unittest.TestCase):
    def test_strong_from_shared_digest(self) -> None:
        self.assertEqual(classify_hitl_band(_strong()), "STRONG")

    def test_single_shared_digest_is_uncertain(self) -> None:
        """SEC-018-02: shared_digest:1 alone is not STRONG."""
        d = _decision(signals=["shared_digest:1"])
        self.assertEqual(classify_hitl_band(d), "UNCERTAIN")
        self.assertFalse(should_auto_apply(d, "hitl_uncertain"))

    def test_strong_from_mesh_overlap_t(self) -> None:
        d = _decision(signals=["shared_archive_member", "archive_member_overlap:3"])
        self.assertEqual(classify_hitl_band(d), "STRONG")

    def test_name_near_dupe_is_uncertain_not_strong(self) -> None:
        self.assertEqual(classify_hitl_band(_uncertain()), "UNCERTAIN")

    def test_weak_mesh_plus_name_is_uncertain(self) -> None:
        # ≥1 large mesh + name_near_dupe is UNCERTAIN (ADR D-4) — not STRONG auto
        d = _decision(
            signals=["shared_archive_member", "archive_member_overlap:1", "name_near_dupe"]
        )
        self.assertEqual(classify_hitl_band(d), "UNCERTAIN")
        self.assertFalse(should_auto_apply(d, "hitl_uncertain"))

    def test_keep_separate_is_refuse(self) -> None:
        self.assertEqual(classify_hitl_band(_refuse()), "REFUSE")


class ModeMatrixTests(unittest.TestCase):
    """ac-1…ac-3: MERGE_HITL × band × approved_for_apply."""

    def test_ac1_hitl_all_never_auto_even_strong(self) -> None:
        self.assertFalse(should_auto_apply(_strong(), "hitl_all"))
        self.assertFalse(should_auto_apply(_uncertain(approved=True), "hitl_all"))
        self.assertFalse(should_auto_apply(_refuse(), "hitl_all"))

    def test_ac2_hitl_uncertain_only_strong_approved(self) -> None:
        self.assertTrue(should_auto_apply(_strong(), "hitl_uncertain"))
        self.assertFalse(should_auto_apply(_uncertain(approved=True), "hitl_uncertain"))
        self.assertFalse(
            should_auto_apply(_strong(approved=False), "hitl_uncertain")
        )
        self.assertFalse(should_auto_apply(_refuse(), "hitl_uncertain"))

    def test_ac3_hitl_off_uncertain_only_when_approved_refuse_never(self) -> None:
        self.assertTrue(should_auto_apply(_strong(), "hitl_off"))
        self.assertTrue(should_auto_apply(_uncertain(approved=True), "hitl_off"))
        self.assertFalse(should_auto_apply(_uncertain(approved=False), "hitl_off"))
        self.assertFalse(should_auto_apply(_refuse(), "hitl_off"))
        # Missing-preview / keep_separate never auto
        weak = _decision(
            decision="keep_separate",
            approved=False,
            signals=["name_near_dupe"],
            reason="missing preview on one or both folders",
        )
        self.assertFalse(should_auto_apply(weak, "hitl_off"))


class WriteMergePlansHitlTests(unittest.TestCase):
    """ac-4: audit JSONL always written; auto-queue respects matrix."""

    def _cfg(self, tmp: Path, merge_hitl: str) -> CurateConfig:
        return CurateConfig(
            library_root=str(tmp / "library"),
            work_dir=str(tmp / "work"),
            merge_hitl=merge_hitl,
        )

    def test_hitl_all_apply_writes_audit_queues_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg = self._cfg(tmp, "hitl_all")
            decisions = [_strong(), _uncertain(approved=True), _refuse()]
            result = write_merge_plans(
                cfg, decisions, do_apply=True, run_id="t1"
            )
            self.assertEqual(result["queued_for_manyfold"], 0)
            self.assertEqual(result["merge_hitl"], "hitl_all")
            plans = Path(result["plans_path"])
            self.assertTrue(plans.is_file())
            lines = [json.loads(x) for x in plans.read_text().splitlines() if x.strip()]
            self.assertEqual(len(lines), 3)
            bands = {ln["hitl_band"] for ln in lines}
            self.assertEqual(bands, {"STRONG", "UNCERTAIN", "REFUSE"})
            for ln in lines:
                self.assertEqual(ln["merge_hitl"], "hitl_all")
            pending = Path(result["pending_path"])
            self.assertFalse(pending.is_file() and pending.read_text().strip())

    def test_hitl_uncertain_queues_only_strong(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg = self._cfg(tmp, "hitl_uncertain")
            decisions = [_strong(), _uncertain(approved=True), _refuse()]
            result = write_merge_plans(
                cfg, decisions, do_apply=True, run_id="t2"
            )
            self.assertEqual(result["queued_for_manyfold"], 1)
            pending = Path(result["pending_path"])
            rows = [json.loads(x) for x in pending.read_text().splitlines() if x.strip()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["hitl_band"], "STRONG")
            self.assertEqual(rows[0]["merge_hitl"], "hitl_uncertain")
            # Audit still has all three
            plans = Path(result["plans_path"])
            self.assertEqual(len(plans.read_text().splitlines()), 3)

    def test_hitl_off_queues_strong_and_uncertain_approved(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg = self._cfg(tmp, "hitl_off")
            decisions = [
                _strong(),
                _uncertain(approved=True),
                _uncertain(approved=False),
                _refuse(),
            ]
            result = write_merge_plans(
                cfg, decisions, do_apply=True, run_id="t3"
            )
            self.assertEqual(result["queued_for_manyfold"], 2)
            pending = Path(result["pending_path"])
            rows = [json.loads(x) for x in pending.read_text().splitlines() if x.strip()]
            bands = {r["hitl_band"] for r in rows}
            self.assertEqual(bands, {"STRONG", "UNCERTAIN"})

    def test_dry_run_never_queues_even_hitl_off(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg = self._cfg(tmp, "hitl_off")
            result = write_merge_plans(
                cfg, [_strong()], do_apply=False, run_id="t4"
            )
            self.assertEqual(result["queued_for_manyfold"], 0)
            self.assertTrue(Path(result["plans_path"]).is_file())

    def test_empty_decision_list(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg = self._cfg(tmp, "hitl_all")
            result = write_merge_plans(cfg, [], do_apply=True, run_id="t5")
            self.assertEqual(result["planned"], 0)
            self.assertEqual(result["queued_for_manyfold"], 0)

    def test_invalid_merge_hitl_on_write_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg = CurateConfig(
                library_root=str(tmp / "library"),
                work_dir=str(tmp / "work"),
                merge_hitl="nope",
            )
            with self.assertRaises(InvalidMergeHitlError):
                write_merge_plans(cfg, [_strong()], do_apply=True, run_id="t6")


class LoadConfigMergeHitlTests(unittest.TestCase):
    def test_default_config_is_hitl_all(self) -> None:
        _, curate = load_config(None)
        self.assertEqual(curate.merge_hitl, "hitl_all")

    def test_config_file_invalid_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.json"
            path.write_text(
                json.dumps({"curate": {"merge_hitl": "silent_off"}}),
                encoding="utf-8",
            )
            with self.assertRaises(InvalidMergeHitlError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
