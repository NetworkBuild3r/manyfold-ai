"""AC3 — hot queries use the catalog indexes.

Strategy: SET enable_seqscan = off (deterministic on a small DB) AND seed
200 occurrences + 80 pending containers so a planner that ignored the GUC
would still have a reason to pick the indexes.

INIT-032/SPEC-004
"""

from __future__ import annotations

import json

from sqlalchemy import text

from forge.db.enums import ContainerStatus
from forge.db.models import Occurrence
from tests.helpers import add_blob, add_container, hex_sha


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
    index_nodes = [n for n in nodes if "Index" in n.get("Node Type", "")]
    names = {n.get("Index Name") for n in index_nodes}
    assert index_name in names, f"expected {index_name} in EXPLAIN (saw {names}): {plan}"


def test_occurrences_by_blob_sha_uses_index(session) -> None:
    target = None
    for i in range(200):
        blob = add_blob(session, f"occ-{i}".encode(), sha256=hex_sha(f"occ-{i}".encode()))
        container = add_container(session)
        session.add(
            Occurrence.from_chain(
                blob_sha=blob.sha256,
                container_id=container.id,
                member_chain=(f"m{i}.stl",),
                depth=1,
            )
        )
        if i == 17:
            target = blob.sha256
    session.commit()
    assert target is not None

    session.execute(text("SET enable_seqscan = off"))
    plan = _plan(
        session,
        "SELECT * FROM occurrences WHERE blob_sha = :sha",
        sha=target,
    )
    _assert_index_access(plan, "ix_occurrences_blob_sha")


def test_pending_claim_query_uses_index(session) -> None:
    for i in range(80):
        status = ContainerStatus.pending if i < 50 else ContainerStatus.done
        add_container(session, status=status, format=f"zip-{i}")
    session.commit()

    session.execute(text("SET enable_seqscan = off"))
    plan = _plan(
        session,
        """
        SELECT * FROM containers
        WHERE status = 'pending'
        ORDER BY id
        LIMIT 50
        FOR UPDATE SKIP LOCKED
        """,
    )
    _assert_index_access(plan, "ix_containers_pending_claim")
