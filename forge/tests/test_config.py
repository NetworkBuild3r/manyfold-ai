"""Config: no localhost default; walk requires FORGE_SOURCE_ROOT.

INIT-032/SPEC-004
"""

from __future__ import annotations

import pytest

from forge.config import ConfigError, ForgeConfig, normalize_db_url


def test_normalize_rewrites_postgres_scheme() -> None:
    assert normalize_db_url("postgresql://forge@db/forge") == "postgresql+psycopg://forge@db/forge"
    assert normalize_db_url("postgres://forge@db/forge") == "postgresql+psycopg://forge@db/forge"
    already = "postgresql+psycopg://forge@db/forge"
    assert normalize_db_url(already) == already


def test_source_root_required(monkeypatch) -> None:
    monkeypatch.delenv("FORGE_SOURCE_ROOT", raising=False)
    with pytest.raises(ConfigError, match="FORGE_SOURCE_ROOT"):
        ForgeConfig.from_env().require_source_root()
