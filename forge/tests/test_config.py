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


def test_skip_dirs_default_and_override(monkeypatch) -> None:
    from forge.config import DEFAULT_SKIP_DIR_NAMES, skip_dir_names

    monkeypatch.delenv("FORGE_SKIP_DIRS", raising=False)
    assert skip_dir_names() == frozenset(DEFAULT_SKIP_DIR_NAMES)
    monkeypatch.setenv("FORGE_SKIP_DIRS", ".git,.manyfold")
    assert skip_dir_names() == frozenset({".git", ".manyfold"})
    monkeypatch.setenv("FORGE_SKIP_DIRS", "")
    assert skip_dir_names() == frozenset()


def test_source_root_required(monkeypatch) -> None:
    monkeypatch.delenv("FORGE_SOURCE_ROOT", raising=False)
    with pytest.raises(ConfigError, match="FORGE_SOURCE_ROOT"):
        ForgeConfig.from_env().require_source_root()
