"""SPEC-010 acceptance tests: exact / subset / commons / partial overlap (fake LLM) / overrides.

INIT-032/SPEC-010
"""

from __future__ import annotations

import csv
import io
import json

import pytest

from forge.packs import judge
from forge.packs.llm import LlmConfigError
from forge.packs.resolve import run
from forge.packs.review import export_review, import_overrides, sample
from forge.packs.settings import PacksSettings


def verdict(v: str, conf: float = 0.9, reason: str = "test") -> str:
    return json.dumps({"verdict": v, "confidence": conf, "reason": reason})


def resolve(db, fake=None, **kw):
    return run(db_url=db, endpoint=fake.endpoint if fake else None, use_llm=fake is not None, **kw)


def partial_pair(lib):
    lib.archive("Misc/A/goku.zip", {"s1.stl": "s1", "s2.stl": "s2", "s3.stl": "s3", "a.stl": "a1"})
    lib.archive(
        "Misc/B/goku-v2.rar",
        {"s1.stl": "s1", "s2.stl": "s2", "s3.stl": "s3", "b1.stl": "b1", "b2.stl": "b2"},
    )


# ------------------------------------------------------------------------------ AC1 fixtures


def test_identical_sets_one_pack(lib, migrated_db):
    lib.archive("Anime/X/goku.zip", {"a.stl": "m1", "b.stl": "m2", "c.stl": "m3"})
    lib.archive("Games/Y/goku-copy.rar", {"x/a.stl": "m1", "x/b.stl": "m2", "c2.stl": "m3"})
    res = resolve(migrated_db)
    assert lib.packs_of() == [{"archive:Anime/X/goku.zip", "archive:Games/Y/goku-copy.rar"}]
    assert res.counts["exact_joined"] == 1
    roles = sorted(r[0] for r in lib.rows("SELECT role::text FROM pack_units"))
    assert roles == ["primary", "source"]
    row = lib.rows("SELECT verdict::text, rationale FROM pack_decisions WHERE kind='deterministic'")
    assert row[0][0] == "same_pack" and "identical mesh set" in row[0][1]
    assert lib.scalar("SELECT count(*) FROM pack_containers") == 2


def test_strict_subset_absorbed(lib, migrated_db):
    lib.archive("Misc/big.zip", {"a.stl": "m1", "b.stl": "m2", "c.stl": "m3", "d.stl": "m4"})
    lib.archive("Misc/part.zip", {"a.stl": "m1", "b.stl": "m2"})
    res = resolve(migrated_db)
    assert lib.packs_of() == [{"archive:Misc/big.zip", "archive:Misc/part.zip"}]
    assert res.counts["subset_absorbed"] == 1
    assert lib.scalar(
        "SELECT role::text FROM pack_units WHERE unit_key='archive:Misc/part.zip'"
    ) == ("absorbed")
    assert lib.scalar("SELECT verdict::text FROM pack_decisions WHERE kind='deterministic'") == (
        "absorb"
    )


def test_subset_with_unique_mesh_is_not_absorbed(lib, migrated_db, fake_llm):
    lib.archive("Misc/big.zip", {"a.stl": "m1", "b.stl": "m2", "c.stl": "m3", "d.stl": "m4"})
    lib.archive("Misc/other.zip", {"a.stl": "m1", "own.stl": "own"})
    fake_llm.responder = lambda body: verdict("separate")
    res = resolve(migrated_db, fake_llm)
    assert res.counts.get("subset_absorbed", 0) == 0
    assert len(lib.packs_of()) == 2


def test_commons_only_overlap_is_no_relation(lib, migrated_db, fake_llm):
    for i in range(6):
        lib.archive(f"Misc/fig{i}.zip", {f"fig{i}.stl": f"u{i}", "base_25mm.stl": "BASE"})
    lib.archive("Misc/bases.zip", {"base_25mm.stl": "BASE"})
    res = resolve(migrated_db, fake_llm)
    assert len(lib.packs_of()) == 7
    assert fake_llm.requests == []
    assert res.counts.get("overlap_pairs", 0) == 0
    assert res.counts["commons_blobs"] == 1
    assert res.counts["subset_commons_only"] == 1


def test_partial_overlap_one_llm_call_with_schema(lib, migrated_db, fake_llm):
    partial_pair(lib)
    fake_llm.responder = lambda body: verdict("same_pack", 0.92, "same figure, v2 adds parts")
    res = resolve(migrated_db, fake_llm)
    assert len(fake_llm.requests) == 1
    body = fake_llm.requests[0]["body"]
    assert fake_llm.requests[0]["path"] == "/v1/chat/completions"
    assert body["temperature"] == 0
    assert body["model"] == "fake-qwen"
    rf = body["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"] == judge.SCHEMA
    user = body["messages"][1]["content"]
    assert user.startswith("<evidence>") and "goku.zip" in user
    ev = json.loads(user.removeprefix("<evidence>\n").removesuffix("\n</evidence>"))
    assert ev["shared"]["meshes"] == 3 and ev["a"]["unique_meshes"] == 1
    assert ev["b"]["unique_meshes"] == 2 and ev["containment_count"] == 0.75
    assert ev["shared"]["triangles"] == 300
    assert lib.packs_of() == [{"archive:Misc/A/goku.zip", "archive:Misc/B/goku-v2.rar"}]
    assert res.counts["llm_called"] == 1 and res.counts["llm_joined"] == 1
    d = lib.rows(
        "SELECT verdict::text, confidence, model, input_fingerprint, prompt_hash, needs_review "
        "FROM pack_decisions WHERE kind='llm'"
    )[0]
    assert d[0] == "same_pack" and float(d[1]) == 0.92 and d[2] == "fake-qwen"
    assert len(d[3]) == 64 and d[4] == judge.PROMPT_HASH and d[5] is False


# ------------------------------------------------------------------------------ AC2


def test_llm_env_unset_errors_before_any_write(lib, migrated_db, monkeypatch):
    lib.archive("Misc/a.zip", {"a.stl": "m1"})
    monkeypatch.delenv("FORGE_LLM_URL", raising=False)
    monkeypatch.setenv("FORGE_LLM_MODEL", "m")
    with pytest.raises(LlmConfigError):
        run(db_url=migrated_db)
    assert lib.scalar("SELECT count(*) FROM pack_units") == 0
    monkeypatch.setenv("FORGE_LLM_URL", "http://localhost:11434/v1")
    with pytest.raises(LlmConfigError):
        run(db_url=migrated_db)
    monkeypatch.setenv("FORGE_LLM_URL", "http://192.168.11.161:11434/v1")
    monkeypatch.delenv("FORGE_LLM_MODEL")
    with pytest.raises(LlmConfigError):
        run(db_url=migrated_db)
    assert lib.scalar("SELECT count(*) FROM packs") == 0


@pytest.mark.parametrize(
    "content,error",
    [
        (
            json.dumps({"verdict": "same_pack", "confidence": 0.9, "reason": "x", "keep": "a"}),
            "extra_field:keep",
        ),
        ("not json", "invalid_verdict_json"),
        (json.dumps({"verdict": "merge", "confidence": 0.9, "reason": "x"}), "non_enum_verdict"),
        (json.dumps({"verdict": "same_pack", "reason": "x"}), "missing_field:confidence"),
    ],
)
def test_malformed_response_is_unsure_with_error(lib, migrated_db, fake_llm, content, error):
    partial_pair(lib)
    fake_llm.responder = lambda body: content
    resolve(migrated_db, fake_llm)
    d = lib.rows("SELECT verdict::text, error, needs_review FROM pack_decisions WHERE kind='llm'")
    assert d == [("unsure", error, True)]
    assert len(lib.packs_of()) == 2
    reasons = lib.rows("SELECT review_reasons FROM packs WHERE needs_review")
    assert len(reasons) == 2 and all("pair_unsure" in r[0] for r in reasons)


def test_transport_error_is_retried_next_run(lib, migrated_db, fake_llm):
    partial_pair(lib)
    fake_llm.responder = lambda body: (503, "busy")
    resolve(migrated_db, fake_llm)
    assert len(fake_llm.requests) == 2  # one retry
    fake_llm.responder = lambda body: verdict("same_pack")
    resolve(migrated_db, fake_llm)
    assert len(fake_llm.requests) == 3
    assert len(lib.packs_of()) == 1


# ------------------------------------------------------------------------------ AC3


def test_rerun_without_evidence_change_makes_zero_llm_calls(lib, migrated_db, fake_llm):
    partial_pair(lib)
    fake_llm.responder = lambda body: verdict("same_pack")
    resolve(migrated_db, fake_llm)
    pack_ids = lib.rows("SELECT id FROM packs ORDER BY id")
    assert len(fake_llm.requests) == 1
    res = resolve(migrated_db, fake_llm)
    assert len(fake_llm.requests) == 1
    assert res.counts["llm_cached"] == 1 and res.counts.get("llm_called", 0) == 0
    assert lib.rows("SELECT id FROM packs ORDER BY id") == pack_ids  # stable ids
    # evidence change (new mesh in B) -> new fingerprint -> judged again
    lib.archive("Misc/B/extra.zip", {"s1.stl": "s1", "s2.stl": "s2", "s3.stl": "s3", "n.stl": "n"})
    resolve(migrated_db, fake_llm)
    assert len(fake_llm.requests) >= 2


# ------------------------------------------------------------------------------ AC4


def test_human_override_wins_and_survives_reruns(lib, migrated_db, fake_llm):
    partial_pair(lib)
    lib.archive("Misc/C/unrelated.zip", {"z.stl": "z"})
    fake_llm.responder = lambda body: verdict("same_pack")
    resolve(migrated_db, fake_llm)
    assert len(lib.packs_of()) == 2
    import_overrides(
        [
            {"a": "Misc/A/goku.zip", "b": "Misc/B/goku-v2.rar", "verdict": "separate"},
            {
                "key_a": "archive:Misc/A/goku.zip",
                "key_b": "archive:Misc/C/unrelated.zip",
                "verdict": "same_pack",
                "note": "owner",
            },
            {"a": "Misc/A/goku.zip", "b": "Misc/C/unrelated.zip", "verdict": ""},
        ],
        db_url=migrated_db,
    )
    for _ in range(2):
        res = resolve(migrated_db, fake_llm)
        assert lib.packs_of() == [
            {"archive:Misc/A/goku.zip", "archive:Misc/C/unrelated.zip"},
            {"archive:Misc/B/goku-v2.rar"},
        ]
        assert res.counts["human_same_applied"] == 1
        assert res.counts["human_separate_applied"] == 1
        assert res.counts.get("llm_called", 0) == 0
    assert lib.scalar("SELECT count(*) FROM pack_decisions WHERE kind='human'") == 2


def test_human_separate_blocks_deterministic_join(lib, migrated_db):
    lib.archive("Misc/x.zip", {"a.stl": "m1", "b.stl": "m2"})
    lib.archive("Misc/y.zip", {"a.stl": "m1", "b.stl": "m2"})
    resolve(migrated_db)
    assert len(lib.packs_of()) == 1
    import_overrides(
        [{"a": "Misc/x.zip", "b": "Misc/y.zip", "verdict": "separate"}], db_url=migrated_db
    )
    res = resolve(migrated_db)
    assert len(lib.packs_of()) == 2 and res.counts["exact_blocked"] == 1


def test_review_csv_round_trip(lib, migrated_db, fake_llm):
    partial_pair(lib)
    fake_llm.responder = lambda body: verdict("unsure", 0.3, "cannot tell")
    resolve(migrated_db, fake_llm)
    buf = io.StringIO()
    assert export_review(buf, db_url=migrated_db) == 1
    rows = list(csv.DictReader(io.StringIO(buf.getvalue())))
    assert rows[0]["llm_verdict"] == "unsure" and "goku.zip" in rows[0]["paths_a"]
    rows[0]["verdict"] = "same_pack"
    import_overrides(rows, db_url=migrated_db)
    resolve(migrated_db, fake_llm)
    assert len(lib.packs_of()) == 1
    buf = io.StringIO()
    assert export_review(buf, db_url=migrated_db) == 0


# ------------------------------------------------------------------------------ structure


def _alice(lib):
    lib.loose({"Anime/Alice/datapackage.json": "dp-alice", "Anime/Alice/preview.jpg": "img"})
    lib.archive("Anime/Alice/alice-sfw.zip", {"body.stl": "body"})
    lib.archive("Anime/Alice/alice-nsfw.zip", {"body.stl": "body_nsfw"})  # bigger seed
    lib.archive("Anime/Alice/img.zip", {"render.jpg": "render"})
    lib.archive("Anime/Bob/bob.zip", {"bob.stl": "bob"})


def test_meshless_units_attach_to_the_largest_mesh_unit_of_their_model_root(lib, migrated_db):
    _alice(lib)
    res = resolve(migrated_db)
    assert lib.packs_of() == [
        {"archive:Anime/Alice/alice-nsfw.zip", "archive:Anime/Alice/img.zip", "loose:Anime/Alice"},
        {"archive:Anime/Alice/alice-sfw.zip"},
        {"archive:Anime/Bob/bob.zip"},
    ]
    assert res.counts["coloc_joined"] == 2
    assert lib.scalar("SELECT image_count FROM pack_units WHERE unit_key='loose:Anime/Alice'") == 1


def test_colocate_all_joins_every_unit_of_a_model_root(lib, migrated_db):
    _alice(lib)
    run(db_url=migrated_db, use_llm=False, settings=PacksSettings(colocate="all"))
    assert lib.packs_of() == [
        {
            "archive:Anime/Alice/alice-nsfw.zip",
            "archive:Anime/Alice/alice-sfw.zip",
            "archive:Anime/Alice/img.zip",
            "loose:Anime/Alice",
        },
        {"archive:Anime/Bob/bob.zip"},
    ]
    with pytest.raises(ValueError):
        PacksSettings().with_overrides(colocate="sometimes")


def test_bundle_root_is_not_colocated(lib, migrated_db):
    files = {"Dump/datapackage.json": "dp"}
    for i in range(4):
        files[f"Dump/prod{i}/p{i}.stl"] = f"p{i}"
    lib.loose(files)
    run(db_url=migrated_db, use_llm=False, settings=PacksSettings(bundle_items=3))
    assert len(lib.packs_of()) == 5  # 4 leaf folders + the root folder itself


def test_nested_archive_meshes_belong_to_the_outer_unit(lib, migrated_db):
    lib.archive("Misc/outer.rar", {}, nested={"inner.zip": {"a.stl": "m1", "b.stl": "m2"}})
    lib.archive("Misc/flat.zip", {"a.stl": "m1", "b.stl": "m2"})
    resolve(migrated_db)
    assert lib.packs_of() == [{"archive:Misc/flat.zip", "archive:Misc/outer.rar"}]


def test_incomplete_units_wait_for_a_later_run(lib, migrated_db):
    cid = lib.archive("Misc/pending.zip", {"a.stl": "m1"}, status="pending")
    lib.archive("Misc/done.zip", {"b.stl": "m2"})
    res = resolve(migrated_db)
    assert res.counts["units"] == 2 and res.counts["units_resolvable"] == 1
    assert lib.packs_of() == [{"archive:Misc/done.zip"}]
    lib.set_status(cid, "done")
    resolve(migrated_db)
    assert len(lib.packs_of()) == 2


def test_dry_run_writes_nothing(lib, migrated_db):
    lib.archive("Misc/x.zip", {"a.stl": "m1"})
    lib.archive("Misc/y.zip", {"a.stl": "m1"})
    res = run(db_url=migrated_db, dry_run=True)
    assert res.dry_run and res.counts["exact_joined"] == 1 and res.counts["packs"] == 1
    for table in ("pack_units", "packs", "pack_decisions", "pack_unit_meshes"):
        assert lib.scalar(f"SELECT count(*) FROM {table}") == 0


def test_sample_prints_llm_decisions_with_evidence(lib, migrated_db, fake_llm):
    partial_pair(lib)
    fake_llm.responder = lambda body: verdict("same_pack")
    resolve(migrated_db, fake_llm)
    out = io.StringIO()
    assert sample(40, db_url=migrated_db, out=out) == 1
    rec = json.loads(out.getvalue())
    assert rec["verdict"] == "same_pack" and rec["evidence"]["shared"]["meshes"] == 3
