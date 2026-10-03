"""CLI wiring for ``forge report``. INIT-032/SPEC-009."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.reports.helpers import add_archive_pack
from tests.reports.test_duplicates import SHARED, UNIQUE_A, UNIQUE_B, ZIP_A, ZIP_B, _asmt018

from forge.cli import main


def test_report_help_lists_subcommands(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["report", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "inventory" in out
    assert "duplicates" in out


def test_duplicates_help_lists_flags(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["report", "duplicates", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--format", "--out", "--min-copies", "--limit"):
        assert flag in out


def test_min_copies_rejects_one(capsys) -> None:
    assert main(["report", "duplicates", "--min-copies", "1"]) == 2
    assert "--min-copies" in capsys.readouterr().err


def test_cli_writes_json_md_csv(session, db_url: str, tmp_path: Path, monkeypatch) -> None:
    _asmt018(session)
    monkeypatch.setenv("FORGE_DB_URL", db_url)
    out = tmp_path / "json"
    assert main(["report", "inventory", "--format", "json", "--out", str(out)]) == 0
    assert (out / "inventory.json").is_file()
    assert '"schema_version": 1' in (out / "inventory.json").read_text()
    md = tmp_path / "md"
    assert main(["report", "duplicates", "--format", "md", "--out", str(md), "--limit", "0"]) == 0
    text = (md / "duplicates.md").read_text()
    assert "What I actually have" in text
    assert "0.75" in text
    csv_dir = tmp_path / "csv"
    rc = main(["report", "duplicates", "--format", "csv", "--out", str(csv_dir), "--limit", "0"])
    assert rc == 0
    assert (csv_dir / "duplicates_pairs.csv").read_text().count("\n") >= 2


def test_cli_stdout_json(session, db_url: str, capsys, monkeypatch) -> None:
    add_archive_pack(session, "Misc/a.zip", ZIP_A, [*SHARED, UNIQUE_A])
    add_archive_pack(session, "Misc/b.zip", ZIP_B, [*SHARED, UNIQUE_B])
    session.commit()
    monkeypatch.setenv("FORGE_DB_URL", db_url)
    assert main(["report", "inventory", "--format", "json"]) == 0
    out = capsys.readouterr().out
    assert '"report": "inventory"' in out
    assert '"asmt018"' in out
