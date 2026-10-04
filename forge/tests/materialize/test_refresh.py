"""``forge materialize refresh-datapackage``: only ``keywords`` change, only under v2, atomically.

No libarchive needed: packs, a plan and the v2 files are written directly. INIT-032/SPEC-016
"""

from __future__ import annotations

import json
import os

import pytest
from sqlalchemy import text

from forge.materialize.apply import datapackage
from forge.materialize.guard import GuardError, open_guard
from forge.materialize.keywords import pack_keywords
from forge.materialize.refresh import refresh_datapackages
from tests.materialize.conftest import MatEnv
from tests.packs.lib import Library

TAGS = ["dc", "sanix", "stl", "marvel", "agent-carter", "bust"]


@pytest.fixture
def guard(mat: MatEnv):
    g, _ = open_guard(mat.v2, mat.src, mat.scratch, shared_mount_ack=True)
    return g


def new_plan(mat: MatEnv) -> int:
    with mat.engine.begin() as conn:
        return int(
            conn.execute(
                text(
                    "INSERT INTO materialize_plans (status, layout, tool_version) "
                    "VALUES ('active', 'tree', 'test') RETURNING id"
                )
            ).scalar_one()
        )


def add_pack(
    mat: MatEnv,
    plan: int,
    name: str,
    *,
    tags: list[str],
    tagged: bool = True,
    category: str = "DC",
    directory: str | None = None,
    status: str = "done",
    write_file: bool = True,
    creator: str | None = "Sanix",
    source_tag: str | None = "Cults3D",
) -> tuple[int, str]:
    """A pack row, its materialize_packs row (legacy meta: no tags) and a legacy datapackage."""
    pid = mat.pack(name, category, [], creator=creator, source_tag=source_tag)
    mat.execute(
        "UPDATE packs SET tags = CAST(:t AS text[]), tags_fingerprint = :fp WHERE id = :id",
        t=tags,
        fp="fp" if tagged else None,
        id=pid,
    )
    rel = directory or f"{category}/{name}"
    meta = {"creator": creator, "source_tag": source_tag, "classified": True, "containers": []}
    mat.execute(
        "INSERT INTO materialize_packs (plan_id, pack_id, category, name, dir, status, meta) "
        "VALUES (:p, :id, :c, :n, :d, :s, :m)",
        p=plan,
        id=pid,
        c=category,
        n=name,
        d=rel,
        s=status,
        m=json.dumps(meta, sort_keys=True),
    )
    if write_file:
        d = mat.v2 / rel
        d.mkdir(parents=True, exist_ok=True)
        pack = {"pack_id": pid, "category": category, "name": name, "meta": json.dumps(meta)}
        dp = datapackage(pack, [], [], plan)
        (d / "datapackage.json").write_text(
            json.dumps(dp, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
    return pid, rel


def read_dp(mat: MatEnv, rel: str) -> dict:
    return json.loads((mat.v2 / rel / "datapackage.json").read_text())


def v2_files(mat: MatEnv) -> list[str]:
    return sorted(str(p.relative_to(mat.v2)) for p in mat.v2.rglob("*") if p.is_file())


# ------------------------------------------------------------------------------ keywords


def test_keywords_tagged_packs_use_their_tags_only():
    kw = pack_keywords(category="DC", source_tag="Cults3D", creator="Sanix", tags=TAGS, tagged=True)
    assert kw == TAGS
    assert pack_keywords(
        category="DC", source_tag=None, creator=None, tags=["A", "a", "b"], tagged=True
    ) == ["A", "b"]


def test_keywords_untagged_packs_keep_the_legacy_three():
    kw = pack_keywords(
        category="DC", source_tag="Cults3D", creator="Sanix", tags=["raw", "!new"], tagged=False
    )
    assert kw == ["DC", "Cults3D", "Sanix"]
    assert pack_keywords(
        category="Misc", source_tag=None, creator=None, tags=None, tagged=False
    ) == ["Misc"]


def test_apply_writes_the_tags_as_the_frictionless_keywords_array():
    meta = {"creator": "Sanix", "source_tag": "Cults3D", "tags": TAGS, "tagged": True}
    pack = {"pack_id": 7, "category": "DC", "name": "Agent Carter", "meta": json.dumps(meta)}
    dp = datapackage(pack, [], [], 1)
    assert dp["keywords"] == TAGS and isinstance(dp["keywords"], list)
    legacy = {"pack_id": 7, "category": "DC", "name": "x", "meta": json.dumps({"creator": "Sanix"})}
    assert datapackage(legacy, [], [], 1)["keywords"] == ["DC", "Sanix"]


def test_plan_carries_tags_into_the_pack_meta(mat: MatEnv):
    cid = Library(mat.engine).loose({"DC/Agent Carter/carter.stl": "c"})
    pid = mat.pack("Agent Carter", "DC", [(cid, "primary")], creator="Sanix", source_tag="Cults3D")
    mat.execute(
        "UPDATE packs SET tags = CAST(:t AS text[]), tags_fingerprint = 'fp' WHERE id = :id",
        t=TAGS,
        id=pid,
    )
    mat.plan()
    meta = json.loads(mat.scalar("SELECT meta FROM materialize_packs WHERE pack_id = :p", p=pid))
    assert meta["tags"] == TAGS and meta["tagged"] is True
    assert meta["creator"] == "Sanix" and meta["source_tag"] == "Cults3D"


# ------------------------------------------------------------------------------- refresh


def test_refresh_rewrites_only_keywords_and_syncs_the_plan_meta(mat: MatEnv, guard):
    src_file = mat.write("DC/Agent Carter/carter.stl", b"source bytes")
    before_src = mat.source_snapshot()
    plan = new_plan(mat)
    pid, rel = add_pack(mat, plan, "Agent Carter", tags=TAGS)
    old = read_dp(mat, rel)
    assert old["keywords"] == ["DC", "Cults3D", "Sanix"]  # what apply wrote before tags existed

    res = refresh_datapackages(mat.engine, plan, guard)
    assert res["updated"] == 1 and res["packs"] == 1 and res["sample"] == [rel]
    new = read_dp(mat, rel)
    assert new["keywords"] == TAGS
    assert {k: v for k, v in new.items() if k != "keywords"} == {
        k: v for k, v in old.items() if k != "keywords"
    }  # resources, provenance and forge.* untouched
    assert v2_files(mat) == [f"{rel}/datapackage.json"]  # no temp file left behind
    meta = json.loads(mat.scalar("SELECT meta FROM materialize_packs WHERE pack_id = :p", p=pid))
    assert meta["tags"] == TAGS and meta["tagged"] is True
    assert mat.source_snapshot() == before_src and src_file.read_bytes() == b"source bytes"


def test_refresh_is_idempotent_and_a_second_run_writes_nothing(mat: MatEnv, guard):
    plan = new_plan(mat)
    add_pack(mat, plan, "A", tags=TAGS)
    add_pack(mat, plan, "B", tags=["dc", "stl"])
    assert refresh_datapackages(mat.engine, plan, guard)["updated"] == 2
    writes = guard.writes
    again = refresh_datapackages(mat.engine, plan, guard)
    assert again["updated"] == 0 and again["unchanged"] == 2 and again["plan_meta_synced"] == 0
    assert guard.writes == writes


def test_dry_run_reports_and_writes_nothing(mat: MatEnv, guard):
    plan = new_plan(mat)
    _, rel = add_pack(mat, plan, "A", tags=TAGS)
    before = (mat.v2 / rel / "datapackage.json").read_bytes()
    meta_before = mat.scalar("SELECT meta FROM materialize_packs")
    res = refresh_datapackages(mat.engine, plan, guard, dry_run=True)
    assert res["would_update"] == 1 and res.get("updated", 0) == 0
    assert (mat.v2 / rel / "datapackage.json").read_bytes() == before
    assert mat.scalar("SELECT meta FROM materialize_packs") == meta_before
    assert guard.writes == 0


def test_untagged_packs_keep_their_legacy_keywords(mat: MatEnv, guard):
    plan = new_plan(mat)
    _, rel = add_pack(mat, plan, "A", tags=["raw", "!new"], tagged=False)
    res = refresh_datapackages(mat.engine, plan, guard)
    assert res["unchanged"] == 1 and res.get("updated", 0) == 0
    assert read_dp(mat, rel)["keywords"] == ["DC", "Cults3D", "Sanix"]


def test_scope_flags_and_pack_status(mat: MatEnv, guard):
    plan = new_plan(mat)
    pid_a, rel_a = add_pack(mat, plan, "A", tags=TAGS)
    pid_b, rel_b = add_pack(mat, plan, "B", tags=TAGS)
    _, rel_p = add_pack(mat, plan, "Pending", tags=TAGS, status="pending")
    _, rel_i = add_pack(mat, plan, "Incomplete", tags=TAGS, status="incomplete")
    res = refresh_datapackages(mat.engine, plan, guard, pack_ids=[pid_a, 10**9])
    assert res["updated"] == 1 and res["not_in_plan"] == 1
    assert read_dp(mat, rel_a)["keywords"] == TAGS
    assert read_dp(mat, rel_b)["keywords"] != TAGS
    res = refresh_datapackages(mat.engine, plan, guard, limit=2)  # by pack id: A (done), then B
    assert res["packs"] == 2 and res["unchanged"] == 1 and read_dp(mat, rel_b)["keywords"] == TAGS
    refresh_datapackages(mat.engine, plan, guard)
    assert read_dp(mat, rel_i)["keywords"] == TAGS  # incomplete packs are refreshed too
    assert read_dp(mat, rel_p)["keywords"] != TAGS  # a pack apply has not finished is not


def test_missing_unreadable_and_symlinked_datapackages_are_skipped_never_created(
    mat: MatEnv, guard
):
    secret = mat.write("DC/secret.json", b'{"keywords": ["source"]}')
    plan = new_plan(mat)
    add_pack(mat, plan, "NoFile", tags=TAGS, write_file=False)
    (mat.v2 / "DC/NoFile").mkdir(parents=True)
    _, rel_bad = add_pack(mat, plan, "Bad", tags=TAGS)
    (mat.v2 / rel_bad / "datapackage.json").write_text("not json")
    _, rel_link = add_pack(mat, plan, "Link", tags=TAGS)
    link = mat.v2 / rel_link / "datapackage.json"
    link.unlink()
    os.symlink(secret, link)
    add_pack(mat, plan, "NoDir", tags=TAGS, write_file=False)
    res = refresh_datapackages(mat.engine, plan, guard)
    assert res["missing_datapackage"] == 2 and res["unreadable"] == 2
    assert res.get("updated", 0) == 0 and guard.writes == 0
    assert not (mat.v2 / "DC/NoFile/datapackage.json").exists()
    assert not (mat.v2 / "DC/NoDir").exists()
    assert (mat.v2 / rel_bad / "datapackage.json").read_text() == "not json"
    assert link.is_symlink() and secret.read_bytes() == b'{"keywords": ["source"]}'


def test_a_hostile_plan_path_is_refused_and_nothing_escapes_v2(mat: MatEnv, guard):
    plan = new_plan(mat)
    add_pack(mat, plan, "Evil", tags=TAGS, directory="../escape", write_file=False)
    outside = mat.nas / "escape"
    outside.mkdir()
    (outside / "datapackage.json").write_text('{"keywords": []}')
    with pytest.raises(GuardError):
        refresh_datapackages(mat.engine, plan, guard)
    assert (outside / "datapackage.json").read_text() == '{"keywords": []}'
    assert guard.writes == 0


def test_hardlinked_datapackage_inode_is_never_modified(mat: MatEnv, guard):
    """Replacing the NAME leaves any other name of the old inode (e.g. a source file) intact."""
    plan = new_plan(mat)
    _, rel = add_pack(mat, plan, "A", tags=TAGS)
    path = mat.v2 / rel / "datapackage.json"
    twin = mat.src / "twin.json"
    os.link(path, twin)
    original = twin.read_bytes()
    refresh_datapackages(mat.engine, plan, guard)
    assert twin.read_bytes() == original
    assert path.stat().st_ino != twin.stat().st_ino and read_dp(mat, rel)["keywords"] == TAGS
