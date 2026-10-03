"""AC4 — forge --help lists the stub subcommands. No database required.

INIT-032/SPEC-004
"""

from __future__ import annotations

import pytest

from forge.cli import main
from forge.config import ConfigError, require_db_url

EXPECTED = ("walk", "sweep", "status", "report", "packs", "classify", "materialize", "db")


def test_help_lists_subcommands(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for name in EXPECTED:
        assert name in out, f"{name} missing from forge --help"


def test_stub_exits_2(capsys) -> None:
    assert main(["walk"]) == 2
    err = capsys.readouterr().err
    assert "not implemented" in err


def test_db_url_fails_loud_without_env(monkeypatch) -> None:
    monkeypatch.delenv("FORGE_DB_URL", raising=False)
    with pytest.raises(ConfigError, match="FORGE_DB_URL is not configured"):
        require_db_url()


def test_db_current_fails_loud_without_env(monkeypatch, capsys) -> None:
    monkeypatch.delenv("FORGE_DB_URL", raising=False)
    assert main(["db", "current"]) == 2
    assert "FORGE_DB_URL is not configured" in capsys.readouterr().err
