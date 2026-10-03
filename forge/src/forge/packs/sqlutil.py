"""Small SQL helpers shared by packs and classify: COPY into a table, (re)create temp tables.

INIT-032/SPEC-010
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


def _ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"bad identifier {name!r}")
    return name


def copy_rows(
    conn: Connection, table: str, columns: Sequence[str], rows: Iterable[Sequence]
) -> int:
    """COPY rows into table inside the connection's current transaction."""
    cols = ", ".join(_ident(c) for c in columns)
    raw = conn.connection.driver_connection
    n = 0
    with raw.cursor() as cur:
        with cur.copy(f"COPY {_ident(table)} ({cols}) FROM STDIN") as cp:
            for row in rows:
                cp.write_row(row)
                n += 1
    return n


def temp_table(conn: Connection, name: str, columns: str, *, as_select: str | None = None) -> None:
    """Drop and recreate a session temp table (rows survive commits)."""
    conn.execute(text(f"DROP TABLE IF EXISTS {_ident(name)}"))
    if as_select is None:
        conn.execute(text(f"CREATE TEMP TABLE {name} ({columns})"))
    else:
        conn.execute(text(f"CREATE TEMP TABLE {name} AS {as_select}"))


def analyze(conn: Connection, *names: str) -> None:
    for n in names:
        conn.execute(text(f"ANALYZE {_ident(n)}"))
