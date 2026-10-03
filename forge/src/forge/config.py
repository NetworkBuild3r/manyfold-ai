"""Runtime config from env. No localhost DB default — unset FORGE_DB_URL fails loud.

INIT-032/SPEC-004
"""

from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigError(RuntimeError):
    """Missing or invalid forge configuration."""


def optional_env(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


def normalize_db_url(url: str) -> str:
    """Rewrite postgres:// / postgresql:// to the psycopg v3 dialect.

    Does not invent a host. A URL that already names a driver is left as-is.
    """
    if url.startswith(("postgresql+psycopg://", "postgresql+psycopg:")):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    return url


def require_db_url() -> str:
    url = optional_env("FORGE_DB_URL")
    if not url:
        raise ConfigError(
            "FORGE_DB_URL is not configured. Set a postgresql+psycopg:// URL; "
            "there is no localhost default."
        )
    return normalize_db_url(url)


@dataclass(frozen=True)
class ForgeConfig:
    db_url: str | None
    source_root: str | None
    scratch: str | None
    worker_id: str | None

    @classmethod
    def from_env(cls) -> ForgeConfig:
        return cls(
            db_url=optional_env("FORGE_DB_URL"),
            source_root=optional_env("FORGE_SOURCE_ROOT"),
            scratch=optional_env("FORGE_SCRATCH"),
            worker_id=optional_env("FORGE_WORKER_ID"),
        )

    def require_db_url(self) -> str:
        if not self.db_url:
            raise ConfigError(
                "FORGE_DB_URL is not configured. Set a postgresql+psycopg:// URL; "
                "there is no localhost default."
            )
        return normalize_db_url(self.db_url)

    def require_source_root(self) -> str:
        if not self.source_root:
            raise ConfigError(
                "FORGE_SOURCE_ROOT is not configured (required by walk). There is no default path."
            )
        return self.source_root
