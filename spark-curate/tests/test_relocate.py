"""Tests for in-library MODE=relocate (INIT-025/SPEC-003).

Fixtures only — never touches live NFS ``3D-Prints``.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spark_curate.__main__ import build_parser, main
from spark_curate.config import CurateConfig
from spark_curate.indexable import COMMON_SUBFOLDERS
from spark_curate.relocate import (
    DestJailRefused,
    PRIMARY_DEST,
    PROVENANCE,
    apply_relocate,
    plan_relocate,
    run_relocate,
    validate_dest,
)

GIRL = "AnySTL/Girl Sitting on Dinosaur"
STORM = "Alliance-Stormtrooper_Samurai_NSFW"


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")


def _girl_tree(lib: Path) -> Path:
    dest = lib / "AnySTL" / "Girl Sitting on Dinosaur"
    dest.mkdir(parents=True)
    _touch(dest / STORM / "troop.7z")
    _touch(dest / STORM / "2021-photo.jpg")
    _touch(dest / "18+ 45GB" / "NestedPackA" / "a.stl")
    _touch(dest / "18+ 45GB" / "NestedPackB" / "b.stl")
    _touch(dest / "Cowgirl.stl")
    (dest / "datapackage.json").write_text("{}", encoding="utf-8")
    return dest


class TestRelocateJail(unittest.TestCase):
    def test_ac2_refuses_empty_dot_slash_outside(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lib = Path(td) / "library"
            lib.mkdir()
            (lib / "AnySTL").mkdir()
            cases = ("", ".", "/", "../Etc/Passwd", "/etc/passwd", "AnySTL/../Etc")
            for dest in cases:
                with self.subTest(dest=dest):
                    with self.assertRaises(DestJailRefused):
                        validate_dest(lib, dest)

    def test_cli_jail_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lib = Path(td) / "library"
            lib.mkdir()
            for dest in ("", ".", "/"):
                rc = main(
                    ["--mode", "relocate", "--library", str(lib), "--dest", dest]
                )
                self.assertEqual(rc, 1, msg=repr(dest))

    def test_parser_accepts_mode_relocate_and_dest(self) -> None:
        p = build_parser()
        self.assertIn("relocate", p._option_string_actions["--mode"].choices)
        ns = p.parse_args(
            ["--mode", "relocate", "--dest", PRIMARY_DEST, "--library", "/tmp/x"]
        )
        self.assertEqual(ns.mode, "relocate")
        self.assertEqual(ns.dest, PRIMARY_DEST)
        self.assertFalse(ns.apply)


class TestRelocatePlanner(unittest.TestCase):
    def test_common_subfolders_not_widened(self) -> None:
        self.assertEqual(len(COMMON_SUBFOLDERS), 15)
        self.assertNotIn("chitubox", COMMON_SUBFOLDERS)

    def test_ac1_stormtrooper_lift_depth2(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lib = Path(td) / "library"
            lib.mkdir()
            _girl_tree(lib)
            cfg = CurateConfig(library_root=str(lib))
            result = plan_relocate(cfg, GIRL, run_id="t1")
            lifts = [p for p in result.plans if p["kind"] == "lift"]
            storm = [p for p in lifts if p["source"].endswith(STORM)]
            self.assertEqual(len(storm), 1, msg=lifts)
            self.assertEqual(storm[0]["dest"], f"AnySTL/{STORM}")
            self.assertEqual(len(Path(storm[0]["dest"]).parts), 2)
            self.assertEqual(storm[0]["category"], "AnySTL")
            self.assertEqual(storm[0]["category_source"], "dest_parent")
            self.assertEqual(storm[0]["provenance"], PROVENANCE)

    def test_18plus_bucket_not_lifted_inner_packs_are(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lib = Path(td) / "library"
            lib.mkdir()
            _girl_tree(lib)
            cfg = CurateConfig(library_root=str(lib))
            result = plan_relocate(cfg, GIRL, run_id="t18")
            lifts = [p for p in result.plans if p["kind"] == "lift"]
            names = {p["pack_name"] for p in lifts}
            self.assertNotIn("18+ 45GB", names)
            self.assertIn("NestedPackA", names)
            self.assertIn("NestedPackB", names)
            self.assertIn(STORM, names)

    def test_ac3_collision_hold_never_n(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lib = Path(td) / "library"
            lib.mkdir()
            dest = _girl_tree(lib)
            occupant = lib / "AnySTL" / STORM
            occupant.mkdir()
            _touch(occupant / "existing.stl")
            cfg = CurateConfig(library_root=str(lib))
            result = plan_relocate(cfg, GIRL, run_id="hold")
            storm = [
                p
                for p in result.plans
                if p.get("pack_name") == STORM and p["kind"] == "hold"
            ]
            self.assertEqual(len(storm), 1)
            self.assertEqual(storm[0]["reason"], "collision")
            self.assertNotIn("(2)", json.dumps(result.plans))
            self.assertTrue((dest / STORM).is_dir())
            self.assertFalse(any(" (" in (p.get("dest") or "") for p in result.plans))

    def test_ac4_sibling_inventory_no_move(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lib = Path(td) / "library"
            lib.mkdir()
            dest = _girl_tree(lib)
            sibling_dest = lib / "AnySTL" / "Rogue Dump"
            _touch(sibling_dest / "InnerPack" / "x.stl")
            work = lib / ".spark-curate"
            work.mkdir()
            audit = work / "audit-20260717-221143.jsonl"
            audit.write_text(
                json.dumps(
                    {
                        "applied": True,
                        "source": str(Path("/unorg/AnySTL/ANYSTL - Other NSFW")),
                        "dest": str(sibling_dest),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            cfg = CurateConfig(library_root=str(lib))
            result = run_relocate(cfg, GIRL, do_apply=False, run_id="sib")
            self.assertTrue(result.siblings)
            sib = result.siblings[0]
            self.assertEqual(sib["kind"], "sibling_dump")
            self.assertEqual(sib["dest"], "AnySTL/Rogue Dump")
            self.assertIs(sib["move"], False)
            self.assertTrue(sibling_dest.is_dir())
            self.assertTrue((sibling_dest / "InnerPack" / "x.stl").is_file())
            self.assertTrue((dest / STORM).is_dir())

    def test_ac5_apply0_writes_plan_no_mv(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lib = Path(td) / "library"
            lib.mkdir()
            dest = _girl_tree(lib)
            cfg = CurateConfig(library_root=str(lib))
            result = run_relocate(cfg, GIRL, do_apply=False, run_id="dry")
            self.assertEqual(result.applied, 0)
            self.assertTrue(result.plan_path.is_file())
            self.assertTrue(result.plan_path.name.startswith("relocate-plan-"))
            self.assertTrue((dest / STORM / "troop.7z").is_file())
            self.assertTrue((dest / "Cowgirl.stl").is_file())
            self.assertFalse((lib / "AnySTL" / STORM / "troop.7z").exists())

    def test_leftover_row_keeps_namesake_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lib = Path(td) / "library"
            lib.mkdir()
            _girl_tree(lib)
            cfg = CurateConfig(library_root=str(lib))
            result = plan_relocate(cfg, GIRL, run_id="left")
            leftover = [p for p in result.plans if p["kind"] == "leftover"]
            self.assertEqual(len(leftover), 1)
            names = leftover[0]["leftover_files"]
            self.assertIn("Cowgirl.stl", names)
            self.assertIn("datapackage.json", names)

    def test_apply_on_tmp_fixture_lifts_and_keeps_leftover(self) -> None:
        """apply() is implemented for SPEC-004; tests use tmp only, not live NFS."""
        with tempfile.TemporaryDirectory() as td:
            lib = Path(td) / "library"
            lib.mkdir()
            dest = _girl_tree(lib)
            cfg = CurateConfig(library_root=str(lib))
            planned = plan_relocate(cfg, GIRL, run_id="mv")
            result = apply_relocate(cfg, planned, dest=GIRL)
            self.assertGreaterEqual(result.applied, 1)
            self.assertFalse((dest / STORM).exists())
            self.assertTrue((lib / "AnySTL" / STORM / "troop.7z").is_file())
            self.assertTrue((dest / "Cowgirl.stl").is_file())
            self.assertTrue((dest / "18+ 45GB").is_dir())
            self.assertTrue((lib / "AnySTL" / "NestedPackA" / "a.stl").is_file())

    def test_cli_dry_run_stormtrooper(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lib = Path(td) / "library"
            lib.mkdir()
            dest = _girl_tree(lib)
            rc = main(
                [
                    "--mode",
                    "relocate",
                    "--library",
                    str(lib),
                    "--dest",
                    GIRL,
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue((dest / STORM).is_dir())
            plans = list((lib / ".spark-curate").glob("relocate-plan-*.jsonl"))
            self.assertTrue(plans)
            lines = [
                json.loads(ln)
                for ln in plans[0].read_text(encoding="utf-8").splitlines()
                if ln.strip()
            ]
            storm = [p for p in lines if str(p.get("source", "")).endswith(STORM)]
            self.assertEqual(storm[0]["dest"], f"AnySTL/{STORM}")


if __name__ == "__main__":
    unittest.main()
