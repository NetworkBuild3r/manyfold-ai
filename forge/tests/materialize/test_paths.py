"""Path sanitization and collision handling (pure). INIT-032/SPEC-012."""

from __future__ import annotations

import unicodedata

import pytest

from forge.materialize.paths import (
    DATAPACKAGE,
    MAX_COMPONENT_BYTES,
    Candidate,
    category_dir,
    chain_components,
    is_junk,
    pack_folder_name,
    resolve_collisions,
    sanitize_component,
    sanitize_components,
    strip_archive_suffix,
)

ATTACKS = [
    "..",
    ".",
    "",
    "   ",
    "../../etc/passwd",
    "..\\..\\windows",
    "/abs/path",
    "a\x00b",
    "\x1b[31mred\x1b[0m",
    "line\nbreak",
    "tab\there",
    "\x7fdel",
    ".hidden",
    ".forge-blobs",
    "a/b",
    "x" * 300 + ".stl",
    "é" * 200 + ".stl",  # 2-byte chars: 400 bytes
    "\U0001f600" * 100,  # 4-byte chars
    "\udcff\udcfe.stl",  # lone surrogates (undecodable bytes)
    "e\u0301cole.stl",  # NFD
    "\u202etxt.exe",  # RTL override is printable; kept but harmless as a name
]


@pytest.mark.parametrize("name", ATTACKS)
def test_sanitize_component_is_always_safe(name) -> None:
    out = sanitize_component(name)
    assert out not in ("", ".", "..")
    assert "/" not in out and "\\" not in out and "\x00" not in out
    assert not any(ord(c) < 0x20 or ord(c) == 0x7F for c in out)
    assert not out.startswith(".")
    assert len(out.encode("utf-8")) <= MAX_COMPONENT_BYTES
    assert unicodedata.normalize("NFC", out) == out
    out.encode("utf-8")  # no surrogates survive
    assert sanitize_component(name) == out  # deterministic


def test_long_names_keep_extension_and_stay_unique() -> None:
    a = sanitize_component("a" * 300 + "-one.stl")
    b = sanitize_component("a" * 300 + "-two.stl")
    assert a.endswith(".stl") and b.endswith(".stl")
    assert a != b


def test_nfd_and_nfc_spellings_converge() -> None:
    assert sanitize_component("e\u0301cole.stl") == sanitize_component("\u00e9cole.stl")


@pytest.mark.parametrize(
    "chain",
    [
        ("../../3D-Prints/pwned.stl",),
        ("a/../../b.stl",),
        ("outer.zip", "../../x.stl"),
        ("/etc/passwd",),
        ("..", ".."),
        ("C:\\Windows\\x.stl",),
    ],
)
def test_chain_components_never_yield_traversal(chain) -> None:
    rel = "/".join(sanitize_components(chain_components(chain)))
    parts = rel.split("/")
    assert all(p not in ("", ".", "..") for p in parts)
    assert not rel.startswith("/")


def test_chain_components_nested_archives_become_folders() -> None:
    assert chain_components(("sub/inner.zip", "x/part.stl")) == ["sub", "inner", "x", "part.stl"]
    assert chain_components(("mid.zip", "inner.7z", "model.stl")) == [
        "mid",
        "inner",
        "model.stl",
    ]
    assert chain_components(("a.stl//dup1",)) == ["a.stl"]


@pytest.mark.parametrize(
    ("name", "want"),
    [
        ("inner.zip", "inner"),
        ("Knight.part1.rar", "Knight"),
        ("data.tar.gz", "data"),
        ("x.7z.001", "x.7z"),
        ("noext", "noext"),
        (".zip", ".zip"),
    ],
)
def test_strip_archive_suffix(name, want) -> None:
    assert strip_archive_suffix(name) == want


def test_junk_filter() -> None:
    assert is_junk(["__MACOSX", "parts", "x.stl"])
    assert is_junk(["parts", "._x.stl"])
    assert not is_junk(["parts", "x.stl"])


def test_category_and_pack_folder() -> None:
    assert category_dir("D&D") == "D&D"
    assert category_dir(None) == "Misc"
    assert category_dir("Unknown") == "Misc"
    assert pack_folder_name(None, 7) == "pack-7"
    assert pack_folder_name("  ", 7) == "pack-7"
    assert pack_folder_name("../evil", 7) == "_._evil"
    assert pack_folder_name(".hidden", 7) == "_hidden"


def test_collisions_are_case_insensitive_and_deterministic() -> None:
    a, b, c = "a" * 64, "b" * 64, "c" * 64
    got = resolve_collisions(
        [Candidate("x/Model.stl", a), Candidate("x/model.stl", b), Candidate("x/MODEL.STL", c)],
        "Art/P",
    )
    assert got[a] == "x/Model.stl"
    assert got[b] == "x/model~bbbbbbbb.stl"
    assert got[c] == "x/MODEL~cccccccc.STL"
    assert len({v.casefold() for v in got.values()}) == 3


def test_collision_with_datapackage_and_file_dir_conflicts() -> None:
    a, b, c = "a" * 64, "b" * 64, "c" * 64
    got = resolve_collisions(
        [Candidate(DATAPACKAGE, a), Candidate("x", b), Candidate("x/y.stl", c)], "Art/P"
    )
    assert got[a] == f"datapackage~{a[:8]}.json"
    assert got[b] == "x"
    assert got[c] == f"_conflict~{c[:16]}.stl"


def test_overlong_relative_path_moves_to_long_dir() -> None:
    a = "d" * 64
    deep = "/".join(["z" * 200] * 25) + "/m.stl"
    got = resolve_collisions([Candidate(deep, a)], "Art/P")
    assert got[a] == f"_long/{a[:16]}.stl"
