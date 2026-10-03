"""Alembic wrappers used by `forge db`. Reads FORGE_DB_URL only.

INIT-032/SPEC-004
"""

from __future__ import annotations

import os
from pathlib import Path

from alembic import command
from alembic.config import Config

from forge.config import require_db_url


def alembic_ini_path() -> Path:
    override = os.environ.get("FORGE_ALEMBIC_INI", "").strip()
    if override:
        path = Path(override)
        if not path.is_file():
            raise RuntimeError(f"FORGE_ALEMBIC_INI is not a file: {override}")
        return path
    candidates = (
        Path.cwd() / "alembic.ini",
        Path(__file__).resolve().parents[3] / "alembic.ini",
        Path("/app/alembic.ini"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("alembic.ini not found; set FORGE_ALEMBIC_INI")


def alembic_config() -> Config:
    require_db_url()
    cfg = Config(str(alembic_ini_path()))
    # env.py is the authority for the URL; this keeps alembic.ini empty of hosts.
    return cfg


def upgrade(revision: str = "head") -> None:
    command.upgrade(alembic_config(), revision)


def downgrade(revision: str) -> None:
    command.downgrade(alembic_config(), revision)


def current() -> None:
    command.current(alembic_config(), verbose=True)
