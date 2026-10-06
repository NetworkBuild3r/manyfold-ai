"""Fixtures for pack resolution tests. INIT-032/SPEC-010."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.helpers import CATALOG_TABLES
from tests.packs.lib import MY_TABLES, FakeLlm, Library


@pytest.fixture
def lib(engine) -> Library:
    tables = ", ".join((*CATALOG_TABLES, "pack_units", *MY_TABLES))
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    return Library(engine)


@pytest.fixture
def fake_llm():
    fake = FakeLlm()
    try:
        yield fake
    finally:
        fake.close()
