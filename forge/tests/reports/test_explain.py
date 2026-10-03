"""EXPLAIN-checked plans for the report hot paths. INIT-032/SPEC-009."""

from __future__ import annotations

import json

from sqlalchemy import text
from tests.helpers import add_blob, add_container, hex_sha

from forge.db.models import Occurrence
from forge.reports.sql import EXPLAIN_DUP_GROUP_SQL, EXPLAIN_MESH_OCC_SQL


def _plan(session, sql: str, **params) -> dict:
    row = session.execute(text("EXPLAIN (FORMAT JSON) " + sql), params).scalar_one()
    if isinstance(row, str):
        return json.loads(row)[0]
    return row[0]


def _walk(node: dict):
    yield node
    for child in node.get("Plans", []) or []:
        yield from _walk(child)


def _assert_index_access(plan: dict, index_name: str) -> None:
    nodes = list(_walk(plan["Plan"]))
    names = {n.get("Index Name") for n in nodes if "Index" in n.get("Node Type", "")}
    assert index_name in names, f"expected {index_name} in EXPLAIN (saw {names}): {plan}"


def _assert_blob_sha_join(plan: dict) -> None:
    """Tiny fixtures seq-scan occurrences; the join key must still be blob_sha."""
    nodes = list(_walk(plan["Plan"]))
    conds = " ".join(
        str(n.get(key) or "")
        for n in nodes
        for key in ("Hash Cond", "Index Cond", "Merge Cond", "Join Filter")
    )
    assert "blob_sha" in conds, f"expected blob_sha join in EXPLAIN (saw {conds!r}): {plan}"


def _seed(session, n: int = 80) -> None:
    for i in range(n):
        blob = add_blob(session, f"mesh-{i}".encode(), sha256=hex_sha(f"mesh-{i}".encode()))
        for extra in ("a", "b"):
            container = add_container(session, format=f"zip-{extra}-{i}")
            session.add(
                Occurrence.from_chain(
                    blob_sha=blob.sha256,
                    container_id=container.id,
                    member_chain=(f"{extra}/{i}.stl",),
                    depth=1,
                )
            )
    session.commit()


def test_mesh_occurrence_join_uses_blob_sha_index(session) -> None:
    _seed(session)
    session.execute(text("SET statement_timeout = '15s'"))
    session.execute(text("SET enable_seqscan = off"))
    try:
        plan = _plan(session, EXPLAIN_MESH_OCC_SQL)
        _assert_index_access(plan, "ix_occurrences_blob_sha")
    finally:
        session.execute(text("RESET enable_seqscan"))
        session.execute(text("RESET statement_timeout"))


def test_duplicate_group_joins_occurrences_on_blob_sha(session) -> None:
    _seed(session)
    session.execute(text("SET statement_timeout = '15s'"))
    try:
        plan = _plan(session, EXPLAIN_DUP_GROUP_SQL)
        _assert_blob_sha_join(plan)
    finally:
        session.execute(text("RESET statement_timeout"))
