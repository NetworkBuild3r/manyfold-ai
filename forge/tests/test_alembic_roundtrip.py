"""AC1 — upgrade head creates the catalog; downgrade base removes it.

INIT-032/SPEC-004
"""

from __future__ import annotations

from sqlalchemy import create_engine, text

from forge.db import migrate
from tests.helpers import CATALOG_TABLES


def _existing_tables(url: str) -> set[str]:
    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
                  AND tablename <> 'alembic_version'
                """
            )
        )
        return {row[0] for row in rows}


def test_upgrade_downgrade_roundtrip(db_url: str) -> None:
    try:
        migrate.upgrade("head")
        present = _existing_tables(db_url)
        missing = set(CATALOG_TABLES) - present
        assert not missing, f"upgrade head missing tables: {sorted(missing)}"

        migrate.downgrade("base")
        leftover = _existing_tables(db_url) & set(CATALOG_TABLES)
        assert not leftover, f"downgrade base left tables: {sorted(leftover)}"
    finally:
        migrate.upgrade("head")
    present_again = _existing_tables(db_url)
    missing_again = set(CATALOG_TABLES) - present_again
    assert not missing_again, f"re-upgrade missing tables: {sorted(missing_again)}"
