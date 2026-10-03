"""Shared fixtures. Postgres is required for schema tests; skip loud if unset.

INIT-032/SPEC-004
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from forge.config import normalize_db_url
from tests.helpers import CATALOG_TABLES

MISSING_DB_REASON = (
    "FORGE_TEST_DB_URL is unset — refusing to invent a localhost database. "
    "Set FORGE_TEST_DB_URL to a disposable Postgres URL (CI quality job or a "
    "cluster throwaway DB). Never point this at the 'manyfold' or 'forge' databases."
)


def pytest_configure() -> None:
    url = os.environ.get("FORGE_TEST_DB_URL", "").strip()
    if not url:
        print(f"\n{MISSING_DB_REASON}\n", flush=True)


@pytest.fixture(scope="session")
def db_url() -> str:
    raw = os.environ.get("FORGE_TEST_DB_URL", "").strip()
    if not raw:
        pytest.skip(MISSING_DB_REASON)
    url = normalize_db_url(raw)
    os.environ["FORGE_DB_URL"] = url
    return url


@pytest.fixture(scope="session")
def migrated_db(db_url: str) -> str:
    from forge.db import migrate

    migrate.upgrade("head")
    return db_url


@pytest.fixture
def engine(migrated_db: str):
    return create_engine(migrated_db, pool_pre_ping=True)


@pytest.fixture
def session(engine) -> Session:
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    joined = ", ".join(CATALOG_TABLES)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {joined} RESTART IDENTITY CASCADE"))
    sess = factory()
    try:
        yield sess
        sess.rollback()
    finally:
        sess.close()
