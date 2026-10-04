"""SPEC-011 acceptance tests against a throwaway DB, a temp source root and a fake LLM.

INIT-032/SPEC-011
"""

from __future__ import annotations

import csv
import io
import json

import pytest

from forge.classify import judge
from forge.classify.review import export_review, import_overrides, sample
from forge.classify.run import run as classify
from forge.packs.llm import LlmEndpoint
from forge.packs.resolve import run as resolve
from forge.packs.settings import PacksSettings


def answer(category="Vehicles", name="Blue Thunder Helicopter", creator="", conf=0.9, **extra):
    return json.dumps(
        {
            "category": category,
            "display_name": name,
            "creator": creator,
            "tags": ["helicopter", "movie"],
            "confidence": conf,
            **extra,
        }
    )


@pytest.fixture
def source_root(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    return root


def write_dp(root, folder: str, **dp) -> None:
    d = root / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / "datapackage.json").write_text(json.dumps(dp))


def build(db, fake=None, root=None, **kw):
    resolve(db_url=db, use_llm=False, settings=PacksSettings())
    return classify(
        db_url=db,
        endpoint=fake.endpoint if fake else None,
        use_llm=fake is not None,
        source_root=str(root) if root else "",
        **kw,
    )


def packs(lib):
    return {
        r[0]: r[1:]
        for r in lib.rows(
            """
            SELECT u.unit_key, p.category, p.name, p.creator, p.source_tag, p.tags,
                   p.decided_by, p.needs_review, p.review_reasons
            FROM packs p JOIN pack_units u ON u.pack_id = p.id AND u.role = 'primary'
            """
        )
    }


def test_games_keeps_games_anystl_gets_llm_category_and_source(
    lib, migrated_db, fake_llm, source_root
):
    lib.loose(
        {"Games/Geralt of Rivia/datapackage.json": "dp", "Games/Geralt of Rivia/Body.stl": "g"}
    )
    write_dp(
        source_root,
        "Games/Geralt of Rivia",
        title="Geralt of Rivia",
        keywords=["games", "witcher", "!new"],
        contributors=[{"title": "Sanix", "roles": ["creator"]}],
    )
    lib.loose(
        {
            "AnySTL/BlueThunderHelicopter (2)/datapackage.json": "dp2",
            "AnySTL/BlueThunderHelicopter (2)/rotor.stl": "rotor",
        }
    )
    write_dp(source_root, "AnySTL/BlueThunderHelicopter (2)", keywords=["helicopter", "80s"])
    fake_llm.responder = lambda body: answer()
    res = build(migrated_db, fake_llm, source_root)
    got = packs(lib)
    geralt = got["loose:Games/Geralt of Rivia"]
    assert geralt[:4] == ("Games", "Geralt of Rivia", "Sanix", None)
    assert geralt[4] == ["games", "witcher", "!new"] and geralt[5] == "deterministic"
    heli = got["loose:AnySTL/BlueThunderHelicopter (2)"]
    assert heli[0] == "Vehicles" and heli[3] == "AnySTL" and heli[5] == "llm"
    assert heli[1] == "BlueThunderHelicopter"  # deterministic folder name, '(2)' stripped
    assert heli[4][:2] == ["helicopter", "80s"] and "movie" in heli[4]
    assert len(fake_llm.requests) == 1
    body = fake_llm.requests[0]["body"]
    assert body["response_format"]["json_schema"]["schema"] == judge.SCHEMA
    assert (
        body["response_format"]["json_schema"]["schema"]["properties"]["category"]["enum"][-1]
        == "Misc"
    )
    assert "Unknown" not in json.dumps(judge.SCHEMA)
    assert res.counts["category:Games"] == 1 and res.counts["source:AnySTL"] == 1


def test_same_display_name_in_one_category_gets_distinct_names(lib, migrated_db, source_root):
    lib.archive("DC/Batman (7)/batman.zip", {"a.stl": "b1"})
    lib.archive("DC/Batman (3)/batman.zip", {"b.stl": "b2"})
    lib.archive("DC/Batman/batman.zip", {"c.stl": "b3"})
    write_dp(
        source_root,
        "DC/Batman (7)",
        title="Batman (7)",
        contributors=[{"title": "Sanix", "roles": ["creator"]}],
    )
    lib.loose({"DC/Batman (7)/datapackage.json": "d1"})
    build(migrated_db, root=source_root)
    names = sorted(r[0] for r in lib.rows("SELECT name FROM packs WHERE category = 'DC'"))
    assert len(names) == 3 and len({n.casefold() for n in names}) == 3
    assert all(not n.rstrip().endswith(")") for n in names)
    assert "batman" in names and "Batman - Sanix" in names


def test_monthly_releases_and_placeholder_metadata(lib, migrated_db, source_root):
    root = "D&D/Goon Master Collection"
    lib.loose({f"{root}/datapackage.json": "dp"})
    write_dp(
        source_root,
        root,
        title="unnamed-model",
        keywords=["unknown", "undead"],
        contributors=[{"title": "null", "roles": ["creator"]}],
    )
    lib.archive(f"{root}/GoonMaster 2020-08.part1.rar", {"a.stl": "a"})
    lib.archive(f"{root}/GoonMaster 2020-09.part1.rar", {"b.stl": "b"})
    lib.archive("D&D/Legendary Orcs (Avatars of War)/03 - May 2021.7z.001", {"c.stl": "c"})
    lib.archive("D&D/Legendary Orcs (Avatars of War)/07 - Sept 2021.7z.001", {"d.stl": "d"})
    build(migrated_db, root=source_root)
    got = {r[0]: r[1:] for r in lib.rows("SELECT name, creator, tags FROM packs")}
    assert set(got) == {
        "GoonMaster 2020-08",
        "GoonMaster 2020-09",
        "Legendary Orcs (Avatars of War) - 03 - May 2021",
        "Legendary Orcs (Avatars of War) - 07 - Sept 2021",
    }
    assert got["GoonMaster 2020-08"] == (None, ["undead"])


def test_bundle_root_title_never_names_a_pack(lib, migrated_db, source_root):
    root = "Games/Gaslands Gear Phase Skull"
    files = {f"{root}/datapackage.json": "dp"}
    for i in range(30):
        files[f"{root}/other{i}/x{i}.jpg"] = f"img{i}"
    lib.loose(files)
    write_dp(source_root, root, title="Gaslands Gear Phase Skull")
    lib.archive(f"{root}/Mythic Mugs KS/Bundle 1.zip.001", {"mug.stl": "mug"})
    build(migrated_db, root=source_root)
    names = {r[0] for r in lib.rows("SELECT name FROM packs WHERE mesh_count > 0")}
    assert names == {"Mythic Mugs KS - Bundle 1"}


def test_bundle_root_metadata_never_tags_a_pack(lib, migrated_db, fake_llm, source_root):
    root = "AnySTL/Artisan Guild - Maneater Nagarots"
    files = {f"{root}/datapackage.json": "dp"}
    for i in range(30):
        files[f"{root}/other{i}/x{i}.jpg"] = f"img{i}"
    lib.loose(files)
    write_dp(
        source_root,
        root,
        title="Artisan Guild - Maneater Nagarots",
        keywords=["spacecraft", "galaxy"],
        contributors=[{"title": "3DArtGuy", "roles": ["creator"]}],
    )
    lib.archive(f"{root}/Dragon Trappers Lodge/Abyssal Maw.7z.001", {"maw.stl": "maw"})
    fake_llm.responder = lambda body: answer(category="D&D", name="Abyssal Maw", creator="")
    build(migrated_db, fake_llm, source_root)
    row = lib.rows("SELECT name, creator, tags FROM packs WHERE mesh_count > 0")[0]
    assert row[1] is None and "spacecraft" not in row[2]
    ev = fake_llm.requests[0]["body"]["messages"][1]["content"]
    assert "spacecraft" not in ev and "3DArtGuy" not in ev


def test_category_outside_list_is_unsure_misc_and_in_review_csv(lib, migrated_db, fake_llm):
    lib.archive("Unknown/odd thing/odd.zip", {"odd.stl": "odd"})
    fake_llm.responder = lambda body: answer(category="Unknown")
    build(migrated_db, fake_llm)
    p = packs(lib)["archive:Unknown/odd thing/odd.zip"]
    assert p[0] == "Misc" and p[6] is True and p[7] == ["classify_unsure"]
    err = lib.scalar("SELECT error FROM classify_decisions WHERE decided_by = 'llm'")
    assert err == "category_not_in_list:Unknown"
    buf = io.StringIO()
    assert export_review(buf, db_url=migrated_db) == 1
    row = next(csv.DictReader(io.StringIO(buf.getvalue())))
    assert row["unit_key"] == "archive:Unknown/odd thing/odd.zip"


def test_low_confidence_goes_to_misc_with_review(lib, migrated_db, fake_llm):
    lib.archive("AnySTL/maybe/maybe.zip", {"m.stl": "m"})
    fake_llm.responder = lambda body: answer(category="Art", conf=0.3)
    build(migrated_db, fake_llm)
    p = packs(lib)["archive:AnySTL/maybe/maybe.zip"]
    assert p[0] == "Misc" and p[7] == ["classify_low_confidence"] and p[3] == "AnySTL"


def test_rerun_unchanged_makes_zero_llm_calls_and_is_idempotent(lib, migrated_db, fake_llm):
    lib.archive("AnySTL/heli/heli.zip", {"m.stl": "m"})
    lib.archive("Anime/goku/goku.zip", {"g.stl": "g"})
    fake_llm.responder = lambda body: answer()
    build(migrated_db, fake_llm)
    before = packs(lib)
    res = build(migrated_db, fake_llm)
    assert len(fake_llm.requests) == 1
    assert res.counts["cached"] == 2 and res.counts.get("llm_called", 0) == 0
    assert packs(lib) == before


def test_a_changed_model_name_neither_invalidates_the_cache_nor_loses_the_audit_column(
    lib, migrated_db, fake_llm
):
    """The model is recorded in `model`, never hashed into a cache key (SPEC-016)."""
    lib.archive("AnySTL/heli/heli.zip", {"m.stl": "m"})
    fake_llm.responder = lambda body: answer()
    build(migrated_db, fake_llm)

    class Renamed:
        endpoint = LlmEndpoint(url=fake_llm.url, model="Qwen/Some-Newer-Model")

    res = build(migrated_db, Renamed)
    assert len(fake_llm.requests) == 1 and res.counts["cached"] == 1
    assert {
        r[0] for r in lib.rows("SELECT model FROM classify_decisions WHERE model IS NOT NULL")
    } == {"fake-qwen"}


def test_decision_rows_record_the_model_resolved_after_a_404(lib, migrated_db, fake_llm):
    lib.archive("AnySTL/heli/heli.zip", {"m.stl": "m"})
    fake_llm.responder = lambda body: answer()
    fake_llm.models, fake_llm.serves = ["served-now"], {"served-now"}

    class Stale:
        endpoint = LlmEndpoint(url=fake_llm.url, model="served-before")

    build(migrated_db, Stale)
    assert [r["body"]["model"] for r in fake_llm.requests] == ["served-before", "served-now"]
    models = {
        r[0] for r in lib.rows("SELECT model FROM classify_decisions WHERE model IS NOT NULL")
    }
    assert models == {"served-now"}


def test_human_override_round_trip_wins(lib, migrated_db, fake_llm):
    lib.archive("Unknown/x/x.zip", {"x.stl": "x"})
    fake_llm.responder = lambda body: answer(category="Unknown")
    build(migrated_db, fake_llm)
    buf = io.StringIO()
    export_review(buf, db_url=migrated_db)
    rows = list(csv.DictReader(io.StringIO(buf.getvalue())))
    rows[0]["set_category"] = "Terrain"
    rows[0]["set_name"] = "Ruined Tower (2)"
    rows[0]["set_tags"] = "ruins;tower"
    assert import_overrides(rows, db_url=migrated_db)["imported"] == 1
    build(migrated_db, fake_llm)
    p = packs(lib)["archive:Unknown/x/x.zip"]
    assert p[:2] == ("Terrain", "Ruined Tower") and p[4] == ["ruins", "tower"]
    assert p[5] == "human" and p[6] is False
    with pytest.raises(ValueError):
        import_overrides(
            [{"unit_key": "archive:Unknown/x/x.zip", "category": "Unknown"}], db_url=migrated_db
        )


def test_no_llm_defers_to_misc_and_later_run_classifies(lib, migrated_db, fake_llm):
    lib.archive("AnySTL/heli/heli.zip", {"m.stl": "m"})
    build(migrated_db)
    p = packs(lib)["archive:AnySTL/heli/heli.zip"]
    assert p[0] == "Misc" and p[7] == ["classify_deferred"]
    fake_llm.responder = lambda body: answer()
    build(migrated_db, fake_llm)
    assert packs(lib)["archive:AnySTL/heli/heli.zip"][0] == "Vehicles"


def test_every_pack_gets_a_category_and_a_safe_name(lib, migrated_db, fake_llm):
    lib.archive("Games/a/STL.zip", {"1.stl": "1"})
    lib.archive("Unknown/../weird\x07name./x.zip", {"2.stl": "2"})
    lib.loose({"@untagged/zz/thing.stl": "3"})
    fake_llm.responder = lambda body: answer(category="Tools", name="   ")
    build(migrated_db, fake_llm)
    rows = lib.rows("SELECT category, name FROM packs")
    assert len(rows) == 3
    for cat, name in rows:
        assert cat and name and "/" not in name and not name.endswith((".", " "))
        assert all(ord(c) >= 32 for c in name) and len(name) <= 120


def test_dry_run_writes_nothing(lib, migrated_db):
    lib.archive("Games/a/a.zip", {"1.stl": "1"})
    resolve(db_url=migrated_db, use_llm=False)
    res = classify(db_url=migrated_db, dry_run=True, source_root="")
    assert res.dry_run and res.counts["category:Games"] == 1
    assert lib.scalar("SELECT count(*) FROM packs WHERE category IS NOT NULL") == 0
    assert lib.scalar("SELECT count(*) FROM classify_decisions") == 0


def test_sample_prints_classifications(lib, migrated_db):
    lib.archive("Games/a/a.zip", {"1.stl": "1"})
    build(migrated_db)
    out = io.StringIO()
    assert sample(50, db_url=migrated_db, out=out) == 1
    assert json.loads(out.getvalue())["category"] == "Games"
