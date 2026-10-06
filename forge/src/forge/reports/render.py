"""Render report documents as json, csv, or markdown. INIT-032/SPEC-009."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from io import StringIO
from pathlib import Path
from typing import Any

FORMATS = ("json", "csv", "md")


def render_json(doc: dict[str, Any]) -> str:
    """Stable JSON: insertion order, no key sort, trailing newline."""
    return json.dumps(doc, indent=2, ensure_ascii=False, default=str) + "\n"


def _csv_rows(doc: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Split a report into named tables for CSV (one file per table)."""
    tables: dict[str, list[dict[str, Any]]] = {}
    report = doc.get("report")
    tables["summary"] = [{**doc.get("summary", {}), **doc.get("have", {})}]
    if report == "inventory":
        tables["asmt018"] = [doc.get("asmt018") or {}]
        tables["by_kind"] = list(doc.get("by_kind") or [])
        tables["by_format"] = list(doc.get("by_format") or [])
        tables["by_top_level_folder"] = list(doc.get("by_top_level_folder") or [])
        tables["by_source_tag"] = list(doc.get("by_source_tag") or [])
        tables["archives_vs_loose"] = list(doc.get("archives_vs_loose") or [])
        tables["depth_distribution"] = list(doc.get("depth_distribution") or [])
        tables["failures"] = list(doc.get("failures") or [])
        tables["failed_containers"] = list(doc.get("failed_containers") or [])
        tables["meshes_by_ext"] = list(doc.get("meshes_by_ext") or [])
        tables["stl_triangles"] = [doc.get("stl_triangles") or {}]
    else:
        tables["blobs"] = [
            {**row, "sources": " | ".join(row.get("sources") or [])}
            for row in (doc.get("blobs") or [])
        ]
        tables["pairs"] = [
            {
                **{k: v for k, v in row.items() if k != "shared"},
                "shared_shas": " | ".join(
                    str(item.get("sha256", "")) for item in (row.get("shared") or [])
                ),
                "shared_names": " | ".join(
                    str(item.get("name", "")) for item in (row.get("shared") or [])
                ),
            }
            for row in (doc.get("pairs") or [])
        ]
    return tables


def render_csv_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                keys.append(key)
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=keys, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: _cell(row.get(k)) for k in keys})
    return buf.getvalue()


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def render_md(doc: dict[str, Any]) -> str:
    report = doc.get("report", "report")
    lines = [f"# Forge {report}", ""]
    have = doc.get("have") or {}
    if have:
        lines.append("## What I actually have")
        lines.append("")
        lines.extend(_md_table([have]))
        lines.append("")
    summary = doc.get("summary") or {}
    if summary:
        lines.append("## Summary")
        lines.append("")
        lines.extend(_md_table([summary]))
        lines.append("")
    if report == "inventory":
        for title, key in (
            ("ASMT-018 comparison", "asmt018"),
            ("By kind", "by_kind"),
            ("By format / status", "by_format"),
            ("By top-level folder", "by_top_level_folder"),
            ("By source tag", "by_source_tag"),
            ("Archives vs loose", "archives_vs_loose"),
            ("Nested depth", "depth_distribution"),
            ("Failure reasons", "failures"),
            ("Failed containers", "failed_containers"),
            ("Meshes by extension", "meshes_by_ext"),
        ):
            rows = doc.get(key)
            if key == "asmt018" and isinstance(rows, dict):
                rows = [rows]
            if not rows:
                continue
            lines.append(f"## {title}")
            lines.append("")
            lines.extend(_md_table(list(rows) if not isinstance(rows, list) else rows))
            lines.append("")
        stl = doc.get("stl_triangles")
        if stl:
            lines.append("## STL triangle stats")
            lines.append("")
            lines.extend(_md_table([stl]))
            lines.append("")
    else:
        blobs = doc.get("blobs") or []
        if blobs:
            flat = [{**b, "sources": " · ".join(b.get("sources") or [])} for b in blobs]
            lines.append("## Cross-pack duplicate meshes")
            lines.append("")
            lines.extend(_md_table(flat))
            lines.append("")
        pairs = doc.get("pairs") or []
        if pairs:
            flat = []
            for pair in pairs:
                item = {k: v for k, v in pair.items() if k != "shared"}
                item["shared"] = ", ".join(
                    f"{s.get('name', '')} ({s.get('sha256', '')[:12]})"
                    for s in (pair.get("shared") or [])
                )
                flat.append(item)
            lines.append("## Pack pairs")
            lines.append("")
            lines.extend(_md_table(flat))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _md_table(rows: Iterable[dict[str, Any]]) -> list[str]:
    rows = [r for r in rows if r]
    if not rows:
        return ["_(empty)_"]
    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                keys.append(key)
    header = "| " + " | ".join(keys) + " |"
    sep = "| " + " | ".join("---" for _ in keys) + " |"
    body = ["| " + " | ".join(_md_escape(_cell(row.get(k))) for k in keys) + " |" for row in rows]
    return [header, sep, *body]


def _md_escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def write_report(doc: dict[str, Any], dest: Path, fmt: str) -> list[Path]:
    """Write ``doc`` under *dest* (a directory). Returns paths written.

    JSON is always written when ``fmt == json`` (SPEC-014 input). CSV writes one
    file per table. Markdown is a single file.
    """
    dest.mkdir(parents=True, exist_ok=True)
    name = str(doc.get("report") or "report")
    written: list[Path] = []
    if fmt == "json":
        path = dest / f"{name}.json"
        path.write_text(render_json(doc), encoding="utf-8")
        written.append(path)
    elif fmt == "md":
        path = dest / f"{name}.md"
        path.write_text(render_md(doc), encoding="utf-8")
        written.append(path)
    elif fmt == "csv":
        for table, rows in _csv_rows(doc).items():
            path = dest / f"{name}_{table}.csv"
            path.write_text(render_csv_table(rows), encoding="utf-8")
            written.append(path)
    else:
        raise ValueError(f"unknown format {fmt!r}")
    return written


def render(doc: dict[str, Any], fmt: str) -> str:
    if fmt == "json":
        return render_json(doc)
    if fmt == "md":
        return render_md(doc)
    if fmt == "csv":
        chunks = []
        for table, rows in _csv_rows(doc).items():
            chunks.append(f"# {table}\n{render_csv_table(rows)}")
        return "\n".join(chunks)
    raise ValueError(f"unknown format {fmt!r}")
