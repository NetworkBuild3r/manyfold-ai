"""AC1 — golden fixtures: every member's sha256 equals ground truth and a 7zz reference."""

from __future__ import annotations

import pytest

from forge.engine import Caps

from .conftest import (
    MANIFEST,
    REQUIRE_NATIVE,
    RecordingSink,
    copy_fixture,
    needs_7zz,
    reference_extract,
    run,
    sevenzip,
    tree_snapshot,
)

GOLDEN = sorted(MANIFEST)


def _expected(name: str) -> dict[tuple, dict]:
    return {tuple(m["chain"]): m for m in MANIFEST[name]["members"]}


@pytest.mark.parametrize("name", GOLDEN)
def test_golden_members_match_ground_truth(name, src, scratch, tmp_path):
    spec = MANIFEST[name]
    if spec.get("reader") == "7zz" and sevenzip() is None:
        assert not REQUIRE_NATIVE, "7zz required"
        pytest.skip("7zz not installed")
    paths = copy_fixture(spec["paths"], src)
    before = tree_snapshot(tmp_path, skip=scratch)
    res, sink = run(paths, scratch_dir=scratch)
    assert res.status == "done", res
    assert res.format == spec["format"]
    # A silent fallback would hide a libarchive regression: the reader is part of the contract.
    assert res.reader == spec.get("reader", "libarchive"), res
    got = sink.by_chain()
    want = _expected(name)
    assert set(got) == set(want), f"missing={set(want) - set(got)} extra={set(got) - set(want)}"
    for chain, m in want.items():
        _, sha, size, kind, tri, depth = got[chain]
        assert (sha, size, depth) == (m["sha256"], m["size"], m["depth"]), chain
        if chain[-1].endswith(".stl"):
            assert tri == 12 and kind == "mesh", chain
    assert len(sink.members) == len(want), "a member was reported twice"
    for chain, status in spec.get("nested", {}).items():
        key = tuple(chain.split("/"))
        assert sink.nested_results[key].status == status, (
            key,
            sink.nested_results[key],
        )
    assert sink.refusals == []
    # GR-001 / AC4: nothing outside scratch changed (the source copies are read-only too).
    assert tree_snapshot(tmp_path, skip=scratch) == before


@needs_7zz
@pytest.mark.parametrize("name", [n for n in GOLDEN if MANIFEST[n].get("reader") != "stream"])
def test_golden_matches_reference_extraction(name, src, scratch, tmp_path):
    paths = copy_fixture(MANIFEST[name]["paths"], src)
    res, sink = run(paths, scratch_dir=scratch)
    assert res.status == "done"
    reference = reference_extract(paths, tmp_path / "ref")
    got = {chain: m[1] for chain, m in sink.by_chain().items()}
    assert got == reference


def test_isolated_and_in_process_agree(src, scratch):
    paths = copy_fixture(["basic_rar5_solid.rar"], src)
    a, sa = run(paths, scratch_dir=scratch)
    b, sb = run(paths, scratch_dir=scratch, isolate=False)
    assert (a.status, a.members, a.bytes_read) == (b.status, b.members, b.bytes_read)
    assert sa.members == sb.members


def test_event_order_nested(src, scratch):
    paths = copy_fixture(["zip_in_rar.rar"], src)
    _, sink = run(paths, scratch_dir=scratch)
    ev = sink.events
    i = ev.index("m:inner.zip")
    assert ev[i + 1] == "n:inner.zip"
    j = ev.index("nr:inner.zip")
    inner = [e for e in ev[i + 2 : j]]
    assert inner and all(e.startswith("m:inner.zip/") for e in inner)


def test_member_kinds(src, scratch):
    paths = copy_fixture(["basic.zip"], src)
    _, sink = run(paths, scratch_dir=scratch)
    kinds = {m[0][-1]: m[3] for m in sink.members}
    assert kinds == {
        "models/cube_binary.stl": "mesh",
        "models/cube_ascii.stl": "mesh",
        "images/preview.png": "image",
        "readme.txt": "doc",
        "empty.txt": "doc",
        "data/random.bin": "other",
    }


def test_split_rar_volumes_are_one_stream(src, scratch):
    """Volume set via archive_read_open_filenames: a member spanning volumes hashes whole."""
    spec = MANIFEST["split_rar5"]
    paths = copy_fixture(spec["paths"], src)
    res, sink = run(paths, scratch_dir=scratch)
    assert res.status == "done" and res.reader == "libarchive"
    big = sink.by_chain()[("data/big.bin",)]
    assert big[2] == 110_000


def test_caps_from_env(monkeypatch):
    monkeypatch.setenv("FORGE_CAP_DEPTH", "2")
    monkeypatch.setenv("FORGE_CAP_WALL_SECONDS", "7")
    caps = Caps.from_env()
    assert caps.depth == 2 and caps.wall_seconds == 7 and caps.ratio == 200


def test_recording_sink_protocol():
    from forge.engine import Sink

    assert isinstance(RecordingSink(), object)
    assert {"member", "refused", "nested_archive", "nested_result"} <= set(dir(Sink))
