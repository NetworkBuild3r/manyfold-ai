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


def test_packs_requires_a_subcommand(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["packs"])
    assert exc.value.code == 2
    assert "resolve" in capsys.readouterr().err


def test_sweep_requires_worker_flag(capsys) -> None:
    assert main(["sweep"]) == 2
    assert "--worker" in capsys.readouterr().err


def test_sweep_help_lists_flags(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["sweep", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--worker", "--procs", "--once", "--metrics-port"):
        assert flag in out


def test_sweep_requires_source_root(monkeypatch, capsys) -> None:
    monkeypatch.delenv("FORGE_SOURCE_ROOT", raising=False)
    assert main(["sweep", "--worker", "--once"]) == 2
    assert "FORGE_SOURCE_ROOT" in capsys.readouterr().err


def test_walk_help_lists_flags(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["walk", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--dry-run" in out
    assert "--threads" in out


def test_walk_requires_source_root(monkeypatch, capsys) -> None:
    monkeypatch.delenv("FORGE_SOURCE_ROOT", raising=False)
    monkeypatch.delenv("FORGE_DB_URL", raising=False)
    assert main(["walk", "--dry-run"]) == 2
    assert "FORGE_SOURCE_ROOT" in capsys.readouterr().err


def test_db_url_fails_loud_without_env(monkeypatch) -> None:
    monkeypatch.delenv("FORGE_DB_URL", raising=False)
    with pytest.raises(ConfigError, match="FORGE_DB_URL is not configured"):
        require_db_url()


def test_db_current_fails_loud_without_env(monkeypatch, capsys) -> None:
    monkeypatch.delenv("FORGE_DB_URL", raising=False)
    assert main(["db", "current"]) == 2
    assert "FORGE_DB_URL is not configured" in capsys.readouterr().err
