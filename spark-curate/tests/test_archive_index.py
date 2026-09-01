# Unit tests for archive-member inverted-index scanner.
# Provenance: INIT-018/SPEC-004
from __future__ import annotations

import ast
import inspect
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spark_curate import archive_index as archive_index_mod  # noqa: E402
from spark_curate.archive_index import (  # noqa: E402
    ARCHIVE_INDEX_PREFIX,
    ARCHIVE_INVERT_PREFIX,
    build_archive_index,
    is_junk_member,
    list_zip_members,
    member_signature,
    run_archive_match,
)
from spark_curate.config import CurateConfig  # noqa: E402


def _write_zip(path: Path, members: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def _mesh_sig_from_zip(zip_path: Path, member_name: str) -> str:
    with zipfile.ZipFile(zip_path, "r") as zf:
        info = zf.getinfo(member_name)
        return member_signature(
            Path(member_name).name,
            info.file_size,
            info.CRC,
        )


class MemberSignatureTests(unittest.TestCase):
    def test_canonical_form(self) -> None:
        self.assertEqual(
            member_signature("Hero.stl", 100, 0xABCDEF01),
            "Hero.stl|100|2882400001",
        )

    def test_junk_macosx(self) -> None:
        self.assertTrue(is_junk_member("__MACOSX/._hero.stl"))
        self.assertTrue(is_junk_member("foo/__MACOSX/bar.stl"))
        self.assertFalse(is_junk_member("files/hero.stl"))


class SharedMeshInvertTests(unittest.TestCase):
    def test_two_folders_share_mesh_sig(self) -> None:
        """ac-1: shared mesh CRC+size+name posts both folders on that sig."""
        mesh_bytes = b"solid shared_mesh_fixture\nendsolid\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a = root / "Games" / "Pack A"
            b = root / "Games" / "Pack B"
            a.mkdir(parents=True)
            b.mkdir(parents=True)
            # Same mesh payload in differently named outer wrappers
            _write_zip(a / "wrapper-alpha.zip", {"meshes/shared_hero.stl": mesh_bytes})
            _write_zip(b / "wrapper-beta.zip", {"stl/shared_hero.stl": mesh_bytes})
            # Noise files so folders look like models
            (a / "readme.txt").write_text("a", encoding="utf-8")
            (b / "readme.txt").write_text("b", encoding="utf-8")

            sig = _mesh_sig_from_zip(a / "wrapper-alpha.zip", "meshes/shared_hero.stl")
            cfg = CurateConfig(library_root=str(root), only_categories=["Games"])
            result = build_archive_index(cfg, write_artifacts=True)

            folders = result.folders_for_sig(sig, mesh_only=True)
            self.assertEqual(folders, ["Games/Pack A", "Games/Pack B"])
            shared = result.shared_mesh_sigs("Games/Pack A", "Games/Pack B")
            self.assertIn(sig, shared)


class NoZipReadTests(unittest.TestCase):
    def test_list_zip_members_never_calls_read(self) -> None:
        """ac-2: matching path must not call ZipFile.read."""
        with tempfile.TemporaryDirectory() as tmp:
            zpath = Path(tmp) / "t.zip"
            _write_zip(zpath, {"hero.stl": b"aaa", "note.txt": b"bbb"})

            original_read = zipfile.ZipFile.read
            calls: list[str] = []

            def _guarded_read(self, name, pwd=None):  # noqa: ANN001
                calls.append(str(name))
                return original_read(self, name, pwd)

            zipfile.ZipFile.read = _guarded_read  # type: ignore[method-assign]
            try:
                listing = list_zip_members(zpath, folder_rel="Games/X")
            finally:
                zipfile.ZipFile.read = original_read  # type: ignore[method-assign]

            self.assertIsNone(listing.skip_reason)
            self.assertGreaterEqual(len(listing.members), 1)
            self.assertEqual(calls, [])

    def test_module_source_has_no_read_on_match_path(self) -> None:
        """ac-2 lint: archive_index.py must not call .read( on ZipFile."""
        src = Path(inspect.getsourcefile(archive_index_mod) or "").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "read":
                    self.fail(
                        "archive_index must not call .read(...) on the matching path "
                        f"(line {node.lineno})"
                    )


class CapAndJunkTests(unittest.TestCase):
    def test_member_cap_truncation_and_macosx_ignored(self) -> None:
        """ac-3: member cap + truncation recorded; __MACOSX ignored."""
        with tempfile.TemporaryDirectory() as tmp:
            zpath = Path(tmp) / "capped.zip"
            members = {
                "keep1.stl": b"one",
                "keep2.stl": b"two",
                "keep3.stl": b"three",
                "__MACOSX/._keep1.stl": b"appledouble",
                "__MACOSX/keep2.stl": b"junk",
            }
            _write_zip(zpath, members)
            listing = list_zip_members(zpath, folder_rel="Games/Cap", max_members=2)
            self.assertTrue(listing.truncated)
            self.assertEqual(listing.max_members, 2)
            self.assertEqual(len(listing.members), 2)
            basenames = {m.basename for m in listing.members}
            self.assertTrue(basenames.issubset({"keep1.stl", "keep2.stl", "keep3.stl"}))
            self.assertFalse(any("__macosx" in m.member_path.lower() for m in listing.members))

    def test_bad_zip_skip_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zpath = Path(tmp) / "bad.zip"
            zpath.write_bytes(b"not-a-zip")
            listing = list_zip_members(zpath, folder_rel="Games/Bad")
            self.assertEqual(listing.skip_reason, "bad_zip")
            self.assertEqual(listing.members, [])


class ArtifactPathTests(unittest.TestCase):
    def test_artifacts_under_spark_curate_with_prefix(self) -> None:
        """ac-4: index artifacts land under .spark-curate/ with clear prefixes."""
        mesh_bytes = b"solid art\nendsolid\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "Movie TV" / "Show Pack"
            folder.mkdir(parents=True)
            _write_zip(folder / "pack.zip", {"hero.stl": mesh_bytes})
            cfg = CurateConfig(library_root=str(root), only_categories=["Movie TV"])
            result = run_archive_match(cfg, run_id="testfixture")
            work = cfg.resolved_work_dir()
            self.assertEqual(work, root / ".spark-curate")
            self.assertIsNotNone(result.index_jsonl_path)
            self.assertIsNotNone(result.invert_jsonl_path)
            index_path = Path(result.index_jsonl_path or "")
            invert_path = Path(result.invert_jsonl_path or "")
            self.assertEqual(index_path.parent, work)
            self.assertEqual(invert_path.parent, work)
            self.assertTrue(index_path.name.startswith(f"{ARCHIVE_INDEX_PREFIX}-"))
            self.assertTrue(invert_path.name.startswith(f"{ARCHIVE_INVERT_PREFIX}-"))
            self.assertTrue(index_path.is_file())
            self.assertTrue(invert_path.is_file())
            invert_text = invert_path.read_text(encoding="utf-8")
            self.assertIn("Movie TV/Show Pack", invert_text)


if __name__ == "__main__":
    unittest.main()
