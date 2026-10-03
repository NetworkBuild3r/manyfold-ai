"""CLI wiring for ``forge report site``. INIT-032/SPEC-014."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.site.helpers import fixture_dir

from forge.cli import main


def test_site_help_lists_flags(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["report", "site", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--in" in out
    assert "--out" in out


def test_report_help_lists_site(capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["report", "--help"])
    assert exc.value.code == 0
    assert "site" in capsys.readouterr().out


def test_site_writes_from_fixtures(tmp_path: Path, capsys) -> None:
    out = tmp_path / "site"
    assert main(["report", "site", "--in", str(fixture_dir()), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "index.html" in printed
    assert (out / "index.html").is_file()
    assert "What do I actually have" in (out / "index.html").read_text(encoding="utf-8")


def test_site_missing_reports_exits_2(tmp_path: Path, capsys) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["report", "site", "--in", str(empty), "--out", str(tmp_path / "out")]) == 2
    assert "inventory.json" in capsys.readouterr().err


def test_site_bad_schema_exits_2(tmp_path: Path, capsys) -> None:
    src = tmp_path / "in"
    src.mkdir()
    (src / "inventory.json").write_text(
        '{"schema_version": 2, "report": "inventory"}',
        encoding="utf-8",
    )
    assert main(["report", "site", "--in", str(src), "--out", str(tmp_path / "out")]) == 2
    assert "schema_version" in capsys.readouterr().err
