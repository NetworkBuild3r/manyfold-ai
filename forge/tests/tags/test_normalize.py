"""Tag normalisation: shape, synonyms, singularising, stopwords, caps, merge. No database.

INIT-032/SPEC-016
"""

from __future__ import annotations

import pytest

from forge.tags.normalize import (
    MAX_TAG_LEN,
    MAX_TAGS,
    merge_tags,
    normalise_tag,
    normalise_tags,
    singular_word,
    slugify,
    vocab,
)


@pytest.mark.parametrize(
    "raw,want",
    [
        ("Agent Carter", "agent-carter"),
        ("  Star   Wars!! ", "star-wars"),
        ("Pokémon", "pokemon"),
        ("Rock & Roll", "rock-and-roll"),
        ("don't stop", "dont-stop"),
        ("snake_case-and CamelCase", "snake-case-and-camelcase"),
        ("--weird--", "weird"),
        ("日本語", ""),
        ("", ""),
    ],
)
def test_slugify(raw, want):
    assert slugify(raw) == want


@pytest.mark.parametrize(
    "raw,want",
    [
        ("dnd", "dungeons-and-dragons"),
        ("D&D", "dungeons-and-dragons"),
        ("Dungeons & Dragons", "dungeons-and-dragons"),
        ("dungeons-and-dragons", "dungeons-and-dragons"),
        ("DC Comics", "dc"),
        ("Marvel Comics", "marvel"),
        ("Sci-Fi", "science-fiction"),
        ("LOTR", "lord-of-the-rings"),
        ("The Avengers", "avengers"),
        ("the-lord-of-the-rings", "lord-of-the-rings"),
        ("Pre-Supported", "presupported"),
        ("40k", "warhammer-40000"),
    ],
)
def test_synonyms_and_articles(raw, want):
    assert normalise_tag(raw) == want


@pytest.mark.parametrize(
    "raw,want",
    [
        ("dragons", "dragon"),
        ("Busts", "bust"),
        ("figures", "figure"),
        ("bunnies", "bunny"),
        ("zombies", "zombie"),
        ("witches", "witch"),
        ("boxes", "box"),
        ("elves", "elf"),
        ("wolves", "wolf"),
        ("heroes", "hero"),
        ("ghost-riders", "ghost-rider"),
        ("miniatures", "miniature"),
        ("minis", "miniature"),
        # not plurals / protected names
        ("boss", "boss"),
        ("octopus", "octopus"),
        ("chassis", "chassis"),
        ("x-men", "x-men"),
        ("star-wars", "star-wars"),
        ("avengers", "avengers"),
        ("game-of-thrones", "game-of-thrones"),
        ("anime", "anime"),
        ("3mf", "3mf"),
        ("28mm", "28mm"),
    ],
)
def test_singularise_obvious_plurals_only(raw, want):
    assert normalise_tag(raw) == want


def test_singular_false_keeps_proper_names():
    assert normalise_tag("Minis", singular=False) == "miniature"  # synonyms still apply
    assert normalise_tag("Sculpts", singular=False) == "sculpts"
    assert normalise_tag("Sculpts") == "sculpt"
    assert normalise_tag("Movie TV", singular=False) == "movie-tv"


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "the", "and", "Model", "models", "3D Print", "STL files", "new", "!new", "unknown",
     "@untagged", "2024", "12", "Misc", None, 7, ["x"]],
)  # fmt: skip
def test_names_nothing_is_dropped(raw):
    assert normalise_tag(raw) is None


def test_length_cap_cuts_at_a_word_boundary():
    long = "a-very-long-franchise-name-that-keeps-going-forever"
    got = normalise_tag(long)
    assert got is not None and len(got) <= MAX_TAG_LEN
    assert long.startswith(got) and not got.endswith("-")
    assert got == "a-very-long-franchise-name-that-keeps"
    assert normalise_tag("x" * 80) is None or len(normalise_tag("x" * 80)) <= MAX_TAG_LEN


def test_normalise_tags_dedupes_in_order_and_caps_at_12():
    got = normalise_tags(["Dragons", "dragon", "DnD", "dungeons and dragons", "Fantasy"])
    assert got == ["dragon", "dungeons-and-dragons", "fantasy"]
    many = [f"tag-{i}" for i in range(30)]
    assert normalise_tags(many) == many[:MAX_TAGS]
    assert len(normalise_tags(many, cap=None)) == 30


def test_normalisation_is_idempotent_over_the_whole_vocabulary():
    v = vocab()
    words = [*v.synonyms, *v.synonyms.values(), *v.protect, *v.irregular, *v.irregular.values()]
    for w in words:
        once = normalise_tag(w)
        if once is not None:
            assert normalise_tag(once) == once, w
            assert normalise_tag(once, singular=False) == once, w


def test_vocabulary_is_self_consistent():
    v = vocab()
    assert not set(v.synonyms) & set(v.synonyms.values()), "a canonical tag must not be a key"
    for key in (*v.synonyms, *v.protect, *v.irregular):
        assert slugify(key) == key, f"vocab key {key!r} is not a slug"
    assert not v.stopwords & set(v.synonyms.values())
    for word in v.ie_plurals:
        assert word.endswith("ies") and singular_word(word) == word[:-1]


def test_merge_is_a_stable_union_with_deterministic_first():
    det, base, llm = ["dc", "stl", "has-preview"], ["marvel", "dc"], ["agent-carter", "stl", "bust"]
    got = merge_tags(det, base, llm)
    assert got == ["dc", "stl", "has-preview", "marvel", "agent-carter", "bust"]


def test_merge_owner_overrides_always_win():
    det, base, llm = ["dc", "stl"], ["marvel"], ["wrong-guess", "bust"]
    assert merge_tags(det, base, llm, add=["My Collection"], remove=["Wrong Guess"]) == [
        "dc",
        "stl",
        "marvel",
        "bust",
        "my-collection",
    ]
    # replace beats every derived list; add / remove still apply on top of it
    assert merge_tags(det, base, llm, replace=["Only This", "stl"], add=["extra"]) == [
        "only-this",
        "stl",
        "extra",
    ]
    assert merge_tags(det, base, llm, replace=["a", "b"], remove=["a"]) == ["b"]
    # an owner-added tag is not singularised or dropped by the LLM-oriented rules
    assert merge_tags([], [], [], add=["Sculpts"]) == ["sculpts"]


def test_merge_caps_the_stored_list():
    tags = [f"t{i}" for i in range(80)]
    assert len(merge_tags(tags)) == 40
