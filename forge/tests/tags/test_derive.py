"""Deterministic tag derivation: one explicit rule per function. No database.

INIT-032/SPEC-016
"""

from __future__ import annotations

import pytest

from forge.tags import derive
from forge.tags.derive import PackFacts, derive_tags, tokenize


@pytest.mark.parametrize(
    "text,want",
    [
        ("PreSupported", ["pre", "supported"]),
        ("STLFiles", ["stl", "files"]),
        ("STLs_Supported", ["stls", "supported"]),
        ("Pre-Supported 32mm", ["pre", "supported", "32mm"]),
        ("hero_v2.1", ["hero", "v2", "1"]),
        ("", []),
    ],
)
def test_tokenize(text, want):
    assert tokenize(text) == want


def test_components_skip_macos_debris_and_empties():
    assert derive.components("a//b/._c.stl") == ["a", "b"]
    assert derive.components("__MACOSX/a/b.stl") == []
    assert derive.components("a\\b\\c.stl") == ["a", "b", "c.stl"]


@pytest.mark.parametrize(
    "category,want",
    [
        ("DC", ["dc"]),
        ("D&D", ["dungeons-and-dragons"]),
        ("Movie TV", ["movie-tv"]),
        ("Cartoons", ["cartoons"]),
        ("Misc", []),
        (None, []),
    ],
)
def test_category_tag(category, want):
    assert derive.category_tag(category) == want


def test_creator_and_source_keep_their_names():
    assert derive.creator_tag("Wicked Sculpts") == ["wicked-sculpts"]
    assert derive.creator_tag("Sanix") == ["sanix"]
    assert derive.creator_tag("") == [] and derive.creator_tag(None) == []
    assert derive.creator_tag("3Dfigureprints.com") == ["3dfigureprints"]
    assert derive.creator_tag("nlsinh@gmail.com") == []  # an address is not a tag
    assert derive.creator_tag("@heheSTL") == ["hehestl"]
    assert derive.source_tag("AnySTL") == ["anystl"]
    assert derive.source_tag("Cults3D") == ["cults3d"]


def test_format_tags_are_in_table_order_and_extension_driven():
    paths = ["a/Hero.STL", "a/scene.lys", "a/plate.ctb", "a/x.gcode", "a/y.3mf", "a/z.zip", "a/n"]
    assert derive.format_tags(paths) == ["stl", "3mf", "lychee", "chitubox", "gcode"]
    assert derive.format_tags(["only.png"]) == []
    assert derive.format_tags(["a/b.step", "a/c.STP"]) == ["step"]


@pytest.mark.parametrize(
    "paths,want",
    [
        (["Hero/Supported/body.stl"], ["presupported"]),
        (["Hero/PreSupported/body.stl"], ["presupported"]),
        (["Hero/Pre-Supported/body.stl"], ["presupported"]),
        (["Hero/hero_presupported.stl"], ["presupported"]),
        (["Hero/Unsupported/body.stl"], ["unsupported"]),
        (["Hero/NoSupports/body.stl"], ["unsupported"]),
        (["Hero/non supported/body.stl"], ["unsupported"]),
        (["Hero/Supported/a.stl", "Hero/Unsupported/a.stl"], ["presupported", "unsupported"]),
        (["Hero/with_supports/a.stl"], ["presupported"]),
        (["Hero/body.stl", "Hero/Supports/readme.txt"], []),
        (["Hero/support_guide.pdf"], []),
    ],
)
def test_support_tags(paths, want):
    assert derive.support_tags(paths) == want


@pytest.mark.parametrize(
    "texts,want",
    [
        (["Zatanna 28mm.zip"], ["28mm"]),
        (["Hero_32MM/body.stl"], ["32mm"]),
        (["Hero 75 mm bust.stl"], ["75mm"]),
        (["a/28mm/x.stl", "b/32mm/y.stl"], ["28mm", "32mm"]),
        (["Hero 1:10.stl"], ["scale-1-10"]),
        (["Hero_1_6_scale.stl"], ["scale-1-6"]),
        (["Hero Scale 1-12.stl"], ["scale-1-12"]),
        (["Hero 28mm 1:12"], ["28mm", "scale-1-12"]),
        # not scales
        (["100x100mm tile.stl"], []),
        (["Hero 5000mm.stl"], []),
        (["Hero 1:13.stl"], []),
        (["Hero 11:10.stl"], []),
        (["Part 1 of 10.stl"], []),
        (["Hero 1 10 version.stl"], []),
    ],
)
def test_scale_tags(texts, want):
    assert derive.scale_tags(texts) == want


def test_part_tags_read_mesh_paths_only():
    paths = [
        "Hero/Bust/hero_bust.stl",
        "Hero/parts/Left_Arm.stl",
        "Hero/parts/HeadWithHelmet.stl",
        "Hero/Base.3mf",
        "Hero/weapons/sword.obj",
        "Hero/notes about torso.txt",
        "Hero/shield.jpg",
    ]
    assert derive.part_tags(paths) == ["bust", "base", "head", "arm", "helmet", "weapon"]
    assert derive.part_tags(["Hero/torso_final.stl"]) == ["torso"]
    assert derive.part_tags(["Hero/database.stl", "Hero/basement.stl"]) == []


def test_preview_tag():
    assert derive.preview_tag(["a/b.stl", "a/preview.JPG"]) == ["has-preview"]
    assert derive.preview_tag(["a/b.stl"], image_count=3) == ["has-preview"]
    assert derive.preview_tag(["a/b.stl", "__MACOSX/a/._x.jpg"]) == []


def test_derive_tags_full_rulebook_order_and_dedupe():
    facts = PackFacts(
        category="DC",
        creator="Sanix",
        source_tag="Cults3D",
        name="Agent Carter 32mm",
        unit_paths=("DC/Agent Carter/Agent Carter.zip",),
        member_paths=(
            "Agent Carter/Supported/body.stl",
            "Agent Carter/Supported/Base.stl",
            "Agent Carter/Bust/bust.stl",
            "Agent Carter/Unsupported/body.stl",
            "Agent Carter/preview.png",
            "__MACOSX/Agent Carter/._body.stl",
        ),
    )
    assert derive_tags(facts) == [
        "dc",
        "sanix",
        "cults3d",
        "stl",
        "presupported",
        "unsupported",
        "32mm",
        "bust",
        "base",
        "has-preview",
    ]
    assert derive_tags(facts) == derive_tags(facts)  # deterministic


def test_derive_tags_on_a_bare_pack_is_empty_not_invented():
    assert derive_tags(PackFacts()) == []
    assert derive_tags(PackFacts(category="Misc", member_paths=("a/readme.txt",))) == []
