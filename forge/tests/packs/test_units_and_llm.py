"""Pure (no DB) tests: unit planning, constrained union-find, LLM config + verdict parsing.

INIT-032/SPEC-010
"""

from __future__ import annotations

import json

import pytest

from forge.packs.judge import parse_verdict
from forge.packs.llm import LlmConfigError, LlmEndpoint, map_concurrent
from forge.packs.unionfind import ConstrainedUnionFind
from forge.packs.units import ContainerRow, SourceRow, plan_units


def test_plan_units_model_roots_bundles_and_nesting():
    sources = [
        SourceRow(1, "Anime/Zatanna (3)/datapackage.json", "loose"),
        SourceRow(2, "Anime/Zatanna (3)/Zatanna/Base/Base.stl", "loose"),
        SourceRow(3, "Anime/Zatanna (3)/Zatanna/Legs/Legs.stl", "loose"),
        SourceRow(4, "Anime/Zatanna (3)/zat.zip", "archive"),
        SourceRow(5, "Anime/Zatanna (3)/Alt/datapackage.json", "loose"),
        SourceRow(6, "Anime/Zatanna (3)/Alt/alt.stl", "loose"),
        SourceRow(7, "Loose/thing.stl", "loose"),
        SourceRow(8, "Loose/not-an-archive.zip", "archive"),
    ]
    containers = [
        ContainerRow(10, "archive", 4, None, "done"),
        ContainerRow(11, "nested", 4, 10, "pending"),
        ContainerRow(12, "loose_batch", 1, None, "done"),
        ContainerRow(13, "archive", 8, None, "failed"),
        ContainerRow(14, "loose_batch", 8, None, "done", requeued_from_id=13),
    ]
    cfiles = [(10, 4), (12, 1), (12, 2), (12, 3), (12, 5), (12, 6), (12, 7), (13, 8), (14, 8)]
    units = {u.key: u for u in plan_units(sources, containers, cfiles, bundle_items=24)}
    assert set(units) == {
        "archive:Anime/Zatanna (3)/zat.zip",
        "loose:Anime/Zatanna (3)",
        "loose:Anime/Zatanna (3)/Alt",
        "loose:Loose",
    }
    zat = units["loose:Anime/Zatanna (3)"]
    assert sorted(zat.loose_paths) == [
        "Anime/Zatanna (3)/Zatanna/Base/Base.stl",
        "Anime/Zatanna (3)/Zatanna/Legs/Legs.stl",
        "Anime/Zatanna (3)/datapackage.json",
    ]
    assert zat.coloc == "Anime/Zatanna (3)"
    arch = units["archive:Anime/Zatanna (3)/zat.zip"]
    assert arch.coloc == "Anime/Zatanna (3)" and arch.complete is False  # nested still pending
    assert arch.container_ids == [10, 11]
    assert units["loose:Anime/Zatanna (3)/Alt"].coloc == "Anime/Zatanna (3)/Alt"
    loose = units["loose:Loose"]
    assert loose.coloc is None and sorted(loose.source_file_ids) == [7, 8]

    bundled = {u.key: u for u in plan_units(sources, containers, cfiles, bundle_items=2)}
    assert "loose:Anime/Zatanna (3)/Zatanna/Base" in bundled
    assert bundled["archive:Anime/Zatanna (3)/zat.zip"].coloc is None


def test_union_find_cannot_link_and_size_cap():
    uf = ConstrainedUnionFind(range(1, 7), cannot_link=[(1, 4)])
    assert uf.union(1, 2) and uf.union(3, 4)
    assert not uf.union(2, 3)  # would put 1 and 4 together
    assert uf.find(2) != uf.find(3)
    assert uf.union(5, 6)
    assert not uf.union(1, 5, max_size=3)
    assert uf.union(1, 5, max_size=4)
    assert uf.comp_of()[6] == 1


@pytest.mark.parametrize(
    "url,model,ok",
    [
        (None, "m", False),
        ("  ", "m", False),
        ("http://localhost:11434/v1", "m", False),
        ("http://127.0.0.1:8000/v1", "m", False),
        ("http://[::1]:8000/v1", "m", False),
        ("ftp://192.168.11.161/v1", "m", False),
        ("http://192.168.11.161:11434/v1", None, False),
        ("http://192.168.11.161:11434/v1/", "Qwen/Qwen3.8-Flash-Next", True),
    ],
)
def test_endpoint_from_env(monkeypatch, url, model, ok):
    for name, value in (("FORGE_LLM_URL", url), ("FORGE_LLM_MODEL", model)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    if ok:
        ep = LlmEndpoint.from_env()
        assert ep.completions_url == "http://192.168.11.161:11434/v1/chat/completions"
    else:
        with pytest.raises(LlmConfigError):
            LlmEndpoint.from_env()


def test_parse_verdict_strict():
    ok = parse_verdict(json.dumps({"verdict": "separate", "confidence": 0.8, "reason": "r"}))
    assert ok.verdict == "separate" and ok.error is None
    assert parse_verdict(json.dumps([1])).error == "non_object"
    long = json.dumps({"verdict": "separate", "confidence": 0.8, "reason": "x" * 161})
    assert parse_verdict(long).error == "reason_too_long"
    bad = json.dumps({"verdict": "separate", "confidence": 1.5, "reason": "r"})
    assert parse_verdict(bad).error == "confidence_out_of_range"


def test_map_concurrent_caps_in_flight_and_keeps_order():
    import threading
    import time

    live, peak, lock = [0], [0], threading.Lock()

    def work(i):
        with lock:
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.01)
        with lock:
            live[0] -= 1
        return i * 2

    out = list(map_concurrent(work, range(30), concurrency=16))
    assert [r for _i, r in out] == [i * 2 for i in range(30)]
    assert peak[0] <= 4
