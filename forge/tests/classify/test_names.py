"""Name cleanup, filesystem safety and collision handling (no DB). INIT-032/SPEC-011 AC2 + AC5."""

from __future__ import annotations

import random
import re

import pytest

from forge.classify.names import (
    MAX_BYTES,
    MAX_CHARS,
    NameRequest,
    assign_names,
    clean_name,
    fs_safe,
    is_weak,
)

COUNTER = re.compile(r"\(\s*\d+\s*\)\s*$")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Zatanna (3)", "Zatanna"),
        ("Batman (7)", "Batman"),
        ("Green Lantern Full Body Statue (2)", "Green Lantern Full Body Statue"),
        ("Superman part1", "Superman"),
        ("Lust_from_Fullmetal_Alchemist.zip", "Lust from Fullmetal Alchemist"),
        ("Crossbowmen+pose+1-3+&+25mm+base.zip", "Crossbowmen pose 1-3 & 25mm base"),
        ("Heman parts.part1.rar", "Heman parts"),
        ("T0me of Dem0ns Vol. II.7z.004", "T0me of Dem0ns Vol. II"),
        ("Kaidan3D - 2024-11 - Erza", "Kaidan3D - Erza"),
        ("grayskull-castel20181004-19407", "grayskull-castel -19407"),
        ("attachment_Witchy wife 2", "Witchy wife 2"),
        ("Mug - Copy (2)", "Mug"),
        ("  trailing junk ... -_ ", "trailing junk"),
        ("Iron Man: Mark 85", "Iron Man - Mark 85"),
        ("a/b\\c*d?e", "a b c d e"),
        ("CON", "CON_"),
        (
            "#24_Epic_Miniatures_Norse_Raiders_Pre_&_Unsupported_7z.001",
            "#24 Epic Miniatures Norse Raiders Pre & Unsupported",
        ),
        ("@rchvillain Games - The Trench", "@rchvillain Games - The Trench"),
        ("#25_Epic_Miniatures_Endless_Nightmare", "#25 Epic Miniatures Endless Nightmare"),
    ],
)
def test_clean_name(raw, expected):
    assert clean_name(raw) == expected


def test_weak_names():
    assert is_weak("STL") and is_weak("12") and is_weak("Supported") and not is_weak("Goku")
    assert is_weak("unnamed-model")


def test_dated_alternates_win_when_a_base_name_is_shared():
    reqs = [
        NameRequest(1, "D&D", "GoonMaster", "archive:a", alternates=("GoonMaster 2020-08",)),
        NameRequest(2, "D&D", "GoonMaster", "archive:b", alternates=("GoonMaster 2020-09",)),
        NameRequest(3, "D&D", "Solo", "archive:c", alternates=("Solo 2021-01",)),
    ]
    names = assign_names(reqs)
    assert names == {1: "GoonMaster 2020-08", 2: "GoonMaster 2020-09", 3: "Solo"}
    assert clean_name("GoonMaster 2020-08.part1.rar", keep_dates=True) == "GoonMaster 2020-08"
    assert clean_name("Man Eaters Part 2.part1.rar") == "Man Eaters"
    assert clean_name("Man Eaters Part 2.part1.rar", keep_dates=True) == "Man Eaters Part 2"
    assert clean_name("LOTP_Feb_2022_Abyss_UNSUPPORTED.001") == "LOTP Feb 2022 Abyss UNSUPPORTED"
    assert clean_name("Tanis April 2021 Patreon by @Allstl.z01") == (
        "Tanis April 2021 Patreon by @Allstl"
    )


def _safe(name: str) -> bool:
    return (
        name == fs_safe(name)
        and "/" not in name
        and "\\" not in name
        and not any(ord(c) < 32 or 0x7F <= ord(c) <= 0x9F for c in name)
        and not name.endswith((".", " "))
        and not name.startswith((".", " "))
        and len(name) <= MAX_CHARS
        and len(name.encode()) <= MAX_BYTES
        and not COUNTER.search(name)
    )


def test_fuzzed_names_are_always_safe():
    rng = random.Random(11)
    alphabet = 'abcXYZ019 ._-/\\:*?"<>|()\x00\x07\x1f\x7f\u00e9\u6f22\U0001f600'
    for _ in range(2000):
        raw = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 400)))
        name = clean_name(raw)
        assert name == "" or _safe(name), repr(name)


def test_long_multibyte_name_fits_bytes():
    name = clean_name("漢字" * 200)
    assert len(name) <= MAX_CHARS and len(name.encode()) <= MAX_BYTES


def test_collisions_get_creator_then_source_then_hash_never_counter():
    reqs = [
        NameRequest(1, "DC", "Batman", "archive:a", creator="Sanix"),
        NameRequest(2, "DC", "Batman", "archive:b", creator="Sanix", source="AnySTL"),
        NameRequest(3, "DC", "batman", "archive:c"),
        NameRequest(4, "Anime", "Batman", "archive:d"),
        NameRequest(5, "DC", "Batman", "archive:e", creator="Gambody"),
    ]
    names = assign_names(reqs)
    dc = [names[i] for i in (1, 2, 3, 5)]
    assert len({n.casefold() for n in dc}) == 4
    assert names[1] == "Batman"
    assert names[2] == "Batman - Sanix"
    assert names[3].startswith("batman - ") and len(names[3]) == len("batman - ") + 8
    assert names[5] == "Batman - Gambody"
    assert names[4] == "Batman"  # other category
    assert all(_safe(n) for n in names.values())
    assert assign_names(reqs) == names  # deterministic


def test_existing_names_are_sticky():
    first = assign_names([NameRequest(9, "DC", "Joker", "archive:z")])
    assert first[9] == "Joker"
    again = assign_names(
        [
            NameRequest(1, "DC", "Joker", "archive:a"),
            NameRequest(9, "DC", "Joker", "archive:z", current="Joker"),
        ]
    )
    assert again[9] == "Joker" and again[1] != "Joker"
