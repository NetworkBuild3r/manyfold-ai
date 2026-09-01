# Lightweight unit checks for merge candidate heuristics (no Spark).
# Provenance: INIT-018/SPEC-005 — archive-member signals + STRONG band wiring.
from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spark_curate.archive_index import ArchiveIndexResult  # noqa: E402
from spark_curate.candidates import (  # noqa: E402
    DEFAULT_MESH_OVERLAP_T,
    MergeCandidate,
    build_merge_candidates,
    normalize_model_slug,
    pair_mesh_overlap_counts,
)
from spark_curate.config import CurateConfig, SparkConfig  # noqa: E402
from spark_curate.decide_merge import MergeDecision, decide_merge_pair  # noqa: E402
from spark_curate.walk import ModelFolder  # noqa: E402


def _write_zip(path: Path, members: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def _fake_index(inverted_mesh: dict[str, list[str]]) -> ArchiveIndexResult:
    return ArchiveIndexResult(inverted_mesh=dict(inverted_mesh))


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
            pairs = build_merge_candidates(cfg, scan_archives=False)
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
            pairs = build_merge_candidates(cfg, scan_archives=False)
            self.assertEqual(len(pairs), 1)
            self.assertIn("name_near_dupe", pairs[0].signals)


class ArchiveCandidateWireTests(unittest.TestCase):
    """INIT-018/SPEC-005 ac-1…ac-3 + inverted postings helper."""

    def test_pair_mesh_overlap_counts_uses_postings(self) -> None:
        inverted = {
            "a.stl|10|1": ["Games/Pack A", "Games/Pack B"],
            "b.stl|20|2": ["Games/Pack A", "Games/Pack B"],
            "c.stl|30|3": ["Games/Pack A", "Games/Pack B"],
            "solo.stl|1|9": ["Games/Pack A"],
        }
        counts = pair_mesh_overlap_counts(inverted)
        self.assertEqual(counts[("games/pack a", "games/pack b")], 3)
        self.assertNotIn(("games/pack a",), counts)

    def test_ac1_t_mesh_overlaps_create_candidate_with_archive_signals(self) -> None:
        """≥ T shared mesh member sigs → candidate with archive overlap signal."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "Games" / "Pack Alpha"
            b = root / "Games" / "Pack Beta"
            a.mkdir(parents=True)
            b.mkdir(parents=True)
            (a / "local.stl").write_bytes(b"aaa")
            (b / "local.stl").write_bytes(b"bbb")
            cfg = CurateConfig(library_root=str(root), only_categories=["Games"], max_merge_pairs=50)
            t = DEFAULT_MESH_OVERLAP_T
            inverted = {
                f"mesh{i}.stl|{100 + i}|{i}": ["Games/Pack Alpha", "Games/Pack Beta"]
                for i in range(t)
            }
            pairs = build_merge_candidates(
                cfg,
                archive_index=_fake_index(inverted),
                scan_archives=False,
                mesh_overlap_t=t,
            )
            self.assertEqual(len(pairs), 1)
            sigs = pairs[0].signals
            self.assertIn("shared_archive_member", sigs)
            self.assertIn(f"archive_member_overlap:{t}", sigs)
            self.assertNotIn("name_near_dupe", sigs)

    def test_ac2_single_shared_mesh_does_not_create_candidate(self) -> None:
        """Single shared mesh CRC alone does not create a merge candidate."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "Games" / "Kitbash Host"
            b = root / "Games" / "Unrelated Pack"
            a.mkdir(parents=True)
            b.mkdir(parents=True)
            (a / "a.stl").write_bytes(b"aaa")
            (b / "b.stl").write_bytes(b"bbb")
            cfg = CurateConfig(library_root=str(root), only_categories=["Games"], max_merge_pairs=50)
            inverted = {
                "commons.stl|999|42": ["Games/Kitbash Host", "Games/Unrelated Pack"],
            }
            pairs = build_merge_candidates(
                cfg,
                archive_index=_fake_index(inverted),
                scan_archives=False,
            )
            self.assertEqual(pairs, [])

    def test_ac3_franchise_only_still_no_pair(self) -> None:
        """Franchise-only / no structural still no pair."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "DC" / "Batman Bust"
            b = root / "DC" / "Batman Full Body"
            a.mkdir(parents=True)
            b.mkdir(parents=True)
            (a / "bust.stl").write_bytes(b"aaa")
            (b / "full.stl").write_bytes(b"bbb")
            cfg = CurateConfig(library_root=str(root), only_categories=["DC"], max_merge_pairs=50)
            # Empty inverted index — no archive structural signal either
            pairs = build_merge_candidates(
                cfg,
                archive_index=_fake_index({}),
                scan_archives=False,
            )
            self.assertEqual(pairs, [])

    def test_one_mesh_plus_name_near_dupe_enriches_uncertain_not_strong_threshold(self) -> None:
        """≥1 mesh + name_near_dupe annotates overlap but overlap < T (UNCERTAIN at decide)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "Games" / "Hero Pack"
            b = root / "Games" / "Hero Pack (2)"
            a.mkdir(parents=True)
            b.mkdir(parents=True)
            (a / "model.stl").write_bytes(b"x")
            (b / "model.stl").write_bytes(b"y")
            cfg = CurateConfig(library_root=str(root), only_categories=["Games"], max_merge_pairs=50)
            inverted = {
                "large.stl|5000000|7": ["Games/Hero Pack", "Games/Hero Pack (2)"],
            }
            pairs = build_merge_candidates(
                cfg,
                archive_index=_fake_index(inverted),
                scan_archives=False,
            )
            self.assertEqual(len(pairs), 1)
            self.assertIn("name_near_dupe", pairs[0].signals)
            self.assertIn("shared_archive_member", pairs[0].signals)
            self.assertIn("archive_member_overlap:1", pairs[0].signals)

    def test_live_zips_t_meshes_via_scanner(self) -> None:
        """End-to-end: real zips + scan_archives builds ≥T archive candidate."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "Games" / "Dup A"
            b = root / "Games" / "Dup B"
            a.mkdir(parents=True)
            b.mkdir(parents=True)
            meshes = {f"m{i}.stl": f"solid mesh{i}\nendsolid\n".encode() for i in range(3)}
            _write_zip(a / "pack.zip", meshes)
            _write_zip(b / "pack.zip", meshes)
            (a / "note.txt").write_text("a", encoding="utf-8")
            (b / "note.txt").write_text("b", encoding="utf-8")
            cfg = CurateConfig(library_root=str(root), only_categories=["Games"], max_merge_pairs=50)
            pairs = build_merge_candidates(cfg, scan_archives=True)
            self.assertEqual(len(pairs), 1)
            self.assertIn("shared_archive_member", pairs[0].signals)
            self.assertIn("archive_member_overlap:3", pairs[0].signals)


class ArchiveDecideStrongTests(unittest.TestCase):
    """INIT-018/SPEC-005 ac-4: STRONG archive skips Gemma."""

    def setUp(self) -> None:
        self.spark = SparkConfig()
        self.curate = CurateConfig(min_merge_confidence=0.80)

    def test_ac4_strong_archive_skips_gemma_when_previews_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "Games" / "Pack"
            b = root / "Games" / "Pack (2)"
            a.mkdir(parents=True)
            b.mkdir(parents=True)
            (a / "model.stl").write_bytes(b"a")
            (b / "model.stl").write_bytes(b"b")
            cand = MergeCandidate(
                a=ModelFolder(path=a, category="Games", name="Pack"),
                b=ModelFolder(path=b, category="Games", name="Pack (2)"),
                signals=["shared_archive_member", "archive_member_overlap:3"],
            )
            with patch(
                "spark_curate.decide_merge._preview_jpeg",
                return_value=b"\xff\xd8fakejpeg",
            ), patch("spark_curate.decide_merge.clients.gemma_vision") as gemma:
                d = decide_merge_pair(cand, self.spark, self.curate, Path(tmp) / ".thumbs")
            gemma.assert_not_called()
            self.assertEqual(d.decision, "merge")
            self.assertGreaterEqual(d.confidence, 0.80)
            self.assertTrue(d.approved_for_apply)
            self.assertIn("STRONG", d.reason)

    def test_one_mesh_plus_name_is_uncertain_calls_gemma(self) -> None:
        """(≥1 mesh + name_near_dupe) is UNCERTAIN — not STRONG."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "Games" / "Pack"
            b = root / "Games" / "Pack (2)"
            a.mkdir(parents=True)
            b.mkdir(parents=True)
            (a / "model.stl").write_bytes(b"a")
            (b / "model.stl").write_bytes(b"b")
            cand = MergeCandidate(
                a=ModelFolder(path=a, category="Games", name="Pack"),
                b=ModelFolder(path=b, category="Games", name="Pack (2)"),
                signals=[
                    "name_near_dupe",
                    "shared_archive_member",
                    "archive_member_overlap:1",
                ],
            )
            with patch(
                "spark_curate.decide_merge._preview_jpeg",
                return_value=b"\xff\xd8fakejpeg",
            ), patch(
                "spark_curate.decide_merge.clients.gemma_vision",
                return_value='{"decision":"keep_separate","confidence":0.5,"target":"a","reason":"different"}',
            ) as gemma, patch(
                "spark_curate.decide_merge.clients.curator_json",
                return_value='{"decision":"keep_separate","confidence":0.5,"target":"a","reason":"different"}',
            ), patch(
                "spark_curate.decide_merge.clients.extract_json_object",
                return_value={
                    "decision": "keep_separate",
                    "confidence": 0.5,
                    "target": "a",
                    "reason": "different",
                },
            ):
                d = decide_merge_pair(cand, self.spark, self.curate, Path(tmp) / ".thumbs")
            gemma.assert_called_once()
            self.assertEqual(d.decision, "keep_separate")
            self.assertNotIn("STRONG", d.reason)


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
