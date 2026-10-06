"""Render SPEC-009 JSON reports as a static HTML site. INIT-032/SPEC-014."""

from __future__ import annotations

import json
from html import escape
from importlib.resources import files
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
CHUNK_SIZE = 250
PAGE_SIZE = 50
CSP = "default-src 'self'"

_UNITS = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")


class SiteError(ValueError):
    """User-facing generator failure (exit 2)."""


def e(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def fmt_bytes(value: object) -> str:
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return "0 B"
    if n < 0:
        n = 0
    x = float(n)
    i = 0
    while x >= 1024 and i < len(_UNITS) - 1:
        x /= 1024
        i += 1
    if i == 0:
        return f"{n} B"
    return f"{x:.2f} {_UNITS[i]} ({n})"


def fmt_ratio(value: object) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "0.0000"


def _asset(name: str) -> str:
    return files("forge.site").joinpath("assets", name).read_text(encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SiteError(f"cannot read {path}: {exc}") from exc
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SiteError(f"{path.name} is not JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise SiteError(f"{path.name} must be a JSON object")
    return doc


def _check(doc: dict[str, Any], expected: str, path: Path) -> dict[str, Any]:
    version = doc.get("schema_version")
    if version != SCHEMA_VERSION:
        raise SiteError(f"{path.name}: schema_version {version!r} is not {SCHEMA_VERSION}")
    report = doc.get("report")
    if report != expected:
        raise SiteError(f"{path.name}: report {report!r} is not {expected!r}")
    return doc


def _page(title: str, body: str, *, script: bool = False) -> str:
    js = '  <script src="assets/site.js" defer></script>\n' if script else ""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        f'  <meta http-equiv="Content-Security-Policy" content="{CSP}">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>{e(title)}</title>\n"
        '  <link rel="stylesheet" href="assets/site.css">\n'
        f"{js}"
        "</head>\n"
        "<body>\n"
        f"{body}\n"
        "</body>\n"
        "</html>\n"
    )


def _nav(active: str) -> str:
    links = [
        ("index.html", "Overview"),
        ("inventory.html", "Inventory"),
        ("duplicates.html", "Duplicates"),
    ]
    parts = []
    for href, label in links:
        if href == active:
            parts.append(f"<strong>{e(label)}</strong>")
        else:
            parts.append(f'<a href="{e(href)}">{e(label)}</a>')
    return "<nav>" + " · ".join(parts) + "</nav>"


def _cards(items: list[tuple[str, str]]) -> str:
    bits = ['<div class="cards">']
    for label, value in items:
        bits.append(
            f'<div class="card"><div class="k">{e(label)}</div>'
            f'<div class="v">{e(value)}</div></div>'
        )
    bits.append("</div>")
    return "\n".join(bits)


def _table(headers: list[str], rows: list[list[object]], *, numeric: set[int] | None = None) -> str:
    numeric = numeric or set()
    out = ["<table>", "<thead><tr>"]
    for i, h in enumerate(headers):
        cls = ' class="num"' if i in numeric else ""
        out.append(f"<th{cls}>{e(h)}</th>")
    out.append("</tr></thead><tbody>")
    for row in rows:
        out.append("<tr>")
        for i, cell in enumerate(row):
            if i in numeric:
                cls = ' class="num"'
            elif isinstance(cell, str) and "/" in cell:
                cls = ' class="path"'
            else:
                cls = ""
            out.append(f"<td{cls}>{e(cell)}</td>")
        out.append("</tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def _have_cards(inv: dict[str, Any] | None, dups: dict[str, Any] | None) -> str:
    have: dict[str, Any] = {}
    if inv:
        have.update(inv.get("have") or {})
    if dups:
        have.update(dups.get("have") or {})
    unique_meshes = have.get("unique_meshes", "n/a")
    unique_bytes = have.get("unique_mesh_bytes", have.get("unique_bytes", "n/a"))
    ratio = have.get("duplicate_ratio", "n/a")
    reclaim = have.get("reclaimable_bytes", "n/a")
    items = [
        ("Unique meshes", str(unique_meshes)),
        ("Unique mesh bytes", fmt_bytes(unique_bytes) if unique_bytes != "n/a" else "n/a"),
        ("Duplicate ratio", fmt_ratio(ratio) if ratio != "n/a" else "n/a"),
        ("Reclaimable bytes", fmt_bytes(reclaim) if reclaim != "n/a" else "n/a"),
    ]
    return (
        "<header>\n"
        "<h1>What do I actually have</h1>\n"
        '<p class="sub">Unique meshes and bytes, duplicate ratio, and bytes you '
        "keep if one copy of each cross-pack mesh is retained.</p>\n"
        f"{_cards(items)}\n"
        "</header>"
    )


def _archives_vs_loose(inv: dict[str, Any] | None) -> str:
    rows = list((inv or {}).get("archives_vs_loose") or [])
    if not rows:
        return '<h2>Archives vs loose</h2>\n<p class="note">No archives-vs-loose rows.</p>'
    body = _table(
        ["kind", "files", "bytes"],
        [[r.get("kind"), r.get("files"), fmt_bytes(r.get("bytes"))] for r in rows],
        numeric={1, 2},
    )
    return f"<h2>Archives vs loose</h2>\n{body}"


def _failed_block(inv: dict[str, Any] | None) -> str:
    failures = list((inv or {}).get("failures") or [])
    containers = list((inv or {}).get("failed_containers") or [])
    by_reason: dict[str, list[dict[str, Any]]] = {}
    for row in containers:
        reason = str(row.get("reason") or "unknown")
        by_reason.setdefault(reason, []).append(row)
    bits = ["<h2>Failed containers</h2>"]
    if failures:
        bits.append(
            _table(
                ["kind", "reason", "count"],
                [[r.get("kind"), r.get("reason"), r.get("count")] for r in failures],
                numeric={2},
            )
        )
    if not containers:
        bits.append('<p class="note">No failed-container paths.</p>')
        return "\n".join(bits)
    for reason in sorted(by_reason):
        items = by_reason[reason]
        bits.append(f'<h3 class="reason">{e(reason)} ({len(items)})</h3>')
        bits.append("<ul>")
        for row in items:
            path = row.get("path") or ""
            kind = row.get("kind") or ""
            bits.append(
                f'<li><span class="path">{e(path)}</span> '
                f'<span class="note">({e(kind)})</span></li>'
            )
        bits.append("</ul>")
    return "\n".join(bits)


def _stamp(inv: dict[str, Any] | None, dups: dict[str, Any] | None) -> str:
    stamps = []
    if inv and inv.get("generated_at"):
        stamps.append(f"inventory {inv['generated_at']}")
    if dups and dups.get("generated_at"):
        stamps.append(f"duplicates {dups['generated_at']}")
    if not stamps:
        return ""
    return f'<p class="note">Generated {e(" · ".join(stamps))}</p>'


def _index_html(inv: dict[str, Any] | None, dups: dict[str, Any] | None) -> str:
    body = (
        f"{_have_cards(inv, dups)}\n"
        "<main>\n"
        f"{_nav('index.html')}\n"
        f"{_archives_vs_loose(inv)}\n"
        f"{_failed_block(inv)}\n"
        f"{_stamp(inv, dups)}\n"
        "</main>"
    )
    return _page("What do I actually have — Library Forge", body)


def _inventory_html(inv: dict[str, Any]) -> str:
    sections: list[str] = []
    for title, key, headers, cells in (
        (
            "By kind",
            "by_kind",
            ["kind", "blobs", "unique bytes", "occurrences", "occurrence bytes"],
            lambda r: [
                r.get("kind"),
                r.get("blobs"),
                fmt_bytes(r.get("unique_bytes")),
                r.get("occurrences"),
                fmt_bytes(r.get("occurrence_bytes")),
            ],
        ),
        (
            "By top-level folder",
            "by_top_level_folder",
            ["folder", "files", "bytes", "archives", "loose"],
            lambda r: [
                r.get("folder"),
                r.get("files"),
                fmt_bytes(r.get("bytes")),
                r.get("archives"),
                r.get("loose"),
            ],
        ),
        (
            "By source tag",
            "by_source_tag",
            ["tag", "files", "bytes"],
            lambda r: [r.get("tag") or "(none)", r.get("files"), fmt_bytes(r.get("bytes"))],
        ),
        (
            "Meshes by extension",
            "meshes_by_ext",
            ["ext", "blobs", "unique bytes", "occurrences"],
            lambda r: [
                r.get("ext"),
                r.get("blobs"),
                fmt_bytes(r.get("unique_bytes")),
                r.get("occurrences"),
            ],
        ),
    ):
        rows = list(inv.get(key) or [])
        if not rows:
            continue
        text_cols = {"kind", "folder", "tag", "ext"}
        numeric = {i for i, h in enumerate(headers) if h not in text_cols}
        sections.append(f"<h2>{e(title)}</h2>")
        sections.append(_table(headers, [cells(r) for r in rows], numeric=numeric))
    asmt = inv.get("asmt018") or {}
    if asmt:
        sections.append("<h2>ASMT-018 comparison</h2>")
        sections.append(
            _table(
                ["hashed before", "hashed now", "unique meshes now", "note"],
                [
                    [
                        asmt.get("archived_mesh_members_hashed_before"),
                        asmt.get("archived_mesh_members_hashed_now"),
                        asmt.get("archived_unique_meshes_now"),
                        asmt.get("note"),
                    ]
                ],
            )
        )
    body = (
        f"{_have_cards(inv, None)}\n"
        "<main>\n"
        f"{_nav('inventory.html')}\n"
        f"{_archives_vs_loose(inv)}\n"
        f"{_failed_block(inv)}\n" + "\n".join(sections) + f"\n{_stamp(inv, None)}\n"
        "</main>"
    )
    return _page("Inventory — Library Forge", body)


def _duplicates_html(dups: dict[str, Any]) -> str:
    n = len(dups.get("pairs") or [])
    body = (
        f"{_have_cards(None, dups)}\n"
        "<main>\n"
        f"{_nav('duplicates.html')}\n"
        '<p class="note">Click a pair to expand the shared STL list. Filter matches pack paths. '
        f"{e(n)} pair rows in this report.</p>\n"
        '<div class="toolbar">\n'
        '  <input id="filter" type="search" placeholder="Filter by pack name">\n'
        '  <div class="pager">\n'
        '    <button id="prev" type="button">Prev</button>\n'
        '    <span id="pageinfo"></span>\n'
        '    <button id="next" type="button">Next</button>\n'
        "  </div>\n"
        "</div>\n"
        '<p id="status" class="note"></p>\n'
        "<table>\n"
        '<thead id="heads"><tr>'
        '<th data-key="pack_a">pack a</th>'
        '<th data-key="pack_b">pack b</th>'
        '<th class="num" data-key="shared_meshes">shared</th>'
        '<th class="num" data-key="shared_bytes">bytes</th>'
        '<th class="num" data-key="containment_count">containment</th>'
        '<th data-key="archives_differ">archives differ</th>'
        "</tr></thead>\n"
        '<tbody id="rows"></tbody>\n'
        "</table>\n"
        f"{_stamp(None, dups)}\n"
        "</main>"
    )
    return _page("Duplicates — Library Forge", body, script=True)


def _write_pair_chunks(out: Path, pairs: list[dict[str, Any]]) -> list[Path]:
    dest = out / "data" / "pairs"
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    packs: list[str] = []
    pack_i: dict[str, int] = {}

    def intern(name: str) -> int:
        if name not in pack_i:
            pack_i[name] = len(packs)
            packs.append(name)
        return pack_i[name]

    index_rows: list[list[object]] = []
    chunk_count = 0 if not pairs else (len(pairs) + CHUNK_SIZE - 1) // CHUNK_SIZE
    for chunk_i in range(chunk_count):
        start = chunk_i * CHUNK_SIZE
        chunk = pairs[start : start + CHUNK_SIZE]
        path = dest / f"c{chunk_i:04d}.json"
        path.write_text(
            json.dumps(chunk, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        written.append(path)
        for off, pair in enumerate(chunk):
            index_rows.append(
                [
                    intern(str(pair.get("pack_a") or "")),
                    intern(str(pair.get("pack_b") or "")),
                    int(pair.get("shared_meshes") or 0),
                    int(pair.get("shared_bytes") or 0),
                    float(pair.get("containment_count") or 0),
                    1 if pair.get("archives_differ") else 0,
                    chunk_i,
                    off,
                ]
            )
    meta = {
        "chunkSize": CHUNK_SIZE,
        "chunkCount": chunk_count,
        "pairCount": len(pairs),
        "pageSize": PAGE_SIZE,
    }
    meta_path = dest / "meta.json"
    meta_path.write_text(json.dumps(meta, separators=(",", ":")), encoding="utf-8")
    written.append(meta_path)
    index_path = dest / "index.json"
    index_path.write_text(
        json.dumps({"packs": packs, "rows": index_rows}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    written.append(index_path)
    return written


def render_site(in_dir: Path, out_dir: Path) -> list[Path]:
    """Write static HTML + assets + chunked pair JSON into *out_dir*."""
    if not in_dir.is_dir():
        raise SiteError(f"--in {in_dir} is not a directory")
    inv_path = in_dir / "inventory.json"
    dups_path = in_dir / "duplicates.json"
    inv = _check(_load_json(inv_path), "inventory", inv_path) if inv_path.is_file() else None
    dups = _check(_load_json(dups_path), "duplicates", dups_path) if dups_path.is_file() else None
    if inv is None and dups is None:
        raise SiteError("need inventory.json and/or duplicates.json in --in")

    out_dir.mkdir(parents=True, exist_ok=True)
    assets = out_dir / "assets"
    assets.mkdir(exist_ok=True)
    written: list[Path] = []

    css = assets / "site.css"
    css.write_text(_asset("site.css"), encoding="utf-8")
    written.append(css)
    js = assets / "site.js"
    js.write_text(_asset("site.js"), encoding="utf-8")
    written.append(js)

    index = out_dir / "index.html"
    index.write_text(_index_html(inv, dups), encoding="utf-8")
    written.append(index)

    if inv is not None:
        inv_html = out_dir / "inventory.html"
        inv_html.write_text(_inventory_html(inv), encoding="utf-8")
        written.append(inv_html)

    pairs = list((dups or {}).get("pairs") or [])
    written.extend(_write_pair_chunks(out_dir, pairs))
    dups_html = out_dir / "duplicates.html"
    empty = {"have": {}, "pairs": [], "generated_at": ""}
    dups_html.write_text(_duplicates_html(dups or empty), encoding="utf-8")
    written.append(dups_html)
    return written
