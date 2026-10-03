"""Fixture JSON → HTML: escaping, CSP, snapshots, no external URLs.

INIT-032/SPEC-014
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.site.helpers import fixture_dir

from forge.site.render import CSP, render_site

_EXTERNAL = re.compile(rb"https?://", re.IGNORECASE)


def _render(tmp_path: Path) -> Path:
    out = tmp_path / "site"
    render_site(fixture_dir(), out)
    return out


def test_fixture_writes_expected_pages(tmp_path: Path) -> None:
    out = _render(tmp_path)
    for name in (
        "index.html",
        "inventory.html",
        "duplicates.html",
        "assets/site.css",
        "assets/site.js",
        "data/pairs/meta.json",
        "data/pairs/c0000.json",
        "data/pairs/index.json",
    ):
        assert (out / name).is_file(), name


def test_headline_snapshot(tmp_path: Path) -> None:
    html = (_render(tmp_path) / "index.html").read_text(encoding="utf-8")
    assert "<h1>What do I actually have</h1>" in html
    assert "Unique meshes" in html
    assert "5" in html
    assert "0.3750" in html
    assert "600" in html
    assert "Archives vs loose" in html
    assert "reader_error" in html
    assert "D&amp;D/City of Tarok.part1.rar" in html


def test_script_filename_is_escaped(tmp_path: Path) -> None:
    out = _render(tmp_path)
    for name in ("index.html", "inventory.html", "duplicates.html"):
        html = (out / name).read_text(encoding="utf-8")
        assert "<script>alert(1)</script>" not in html
        assert "<script>evil</script>" not in html
    inv = (out / "inventory.html").read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;.zip" in inv
    chunk = (out / "data/pairs/c0000.json").read_text(encoding="utf-8")
    # JSON holds the raw name; the HTML shell must not.
    assert "<script>alert(1)</script>.stl" in chunk
    dups = (out / "duplicates.html").read_text(encoding="utf-8")
    assert "default-src 'self'" in dups
    assert "&lt;script&gt;evil&lt;/script&gt;" not in dups
    # pack names live in JSON chunks, not the shell HTML
    assert "Games/" not in dups or "pack a" in dups


def test_csp_meta_is_strict(tmp_path: Path) -> None:
    out = _render(tmp_path)
    for name in ("index.html", "inventory.html", "duplicates.html"):
        html = (out / name).read_text(encoding="utf-8")
        assert f'http-equiv="Content-Security-Policy" content="{CSP}"' in html
        assert "unsafe-inline" not in html
        assert "cdn" not in html.lower()


def test_duplicates_uses_external_js_not_inline(tmp_path: Path) -> None:
    html = (_render(tmp_path) / "duplicates.html").read_text(encoding="utf-8")
    assert 'src="assets/site.js"' in html
    assert "<script>" not in html.replace('<script src="assets/site.js" defer></script>', "")


def test_no_external_urls_in_generated_site(tmp_path: Path) -> None:
    out = _render(tmp_path)
    offenders: list[str] = []
    for path in out.rglob("*"):
        if not path.is_file() or path.suffix == ".json":
            continue
        data = path.read_bytes()
        if _EXTERNAL.search(data):
            offenders.append(str(path.relative_to(out)))
    assert offenders == []
