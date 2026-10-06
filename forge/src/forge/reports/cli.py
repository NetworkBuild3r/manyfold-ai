"""``forge report inventory|duplicates`` entry. INIT-032/SPEC-009."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from forge.reports.render import FORMATS, render, write_report
from forge.reports.sql import collect_duplicates, collect_inventory

# Report queries may aggregate the whole catalog; 15 min matches SPEC-009 AC3.
REPORT_STATEMENT_TIMEOUT = "15min"


def _stamp(doc: dict, generated_at: str) -> dict:
    doc["generated_at"] = generated_at
    return doc


def run_report(engine: Engine, args: argparse.Namespace) -> int:
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with engine.connect() as conn:
        # Literal interval — SET does not accept bound parameters.
        conn.execute(text(f"SET statement_timeout = '{REPORT_STATEMENT_TIMEOUT}'"))
        doc = _build(conn, args)
    doc = _stamp(doc, generated_at)
    fmt = args.format
    if args.out:
        written = write_report(doc, Path(args.out), fmt)
        for path in written:
            print(path)
        return 0
    sys.stdout.write(render(doc, fmt))
    return 0


def _build(conn: Connection, args: argparse.Namespace) -> dict:
    if args.report_command == "inventory":
        return collect_inventory(conn)
    if args.report_command == "duplicates":
        return collect_duplicates(
            conn,
            min_copies=args.min_copies,
            min_shared=1,
            limit=args.limit,
        )
    raise ValueError(f"unknown report {args.report_command!r}")


def main_report(args: argparse.Namespace) -> int:
    from forge.config import ConfigError
    from forge.db.session import get_engine

    if args.format not in FORMATS:
        print(f"forge report: unknown --format {args.format!r}", file=sys.stderr)
        return 2
    if args.report_command == "duplicates" and args.min_copies < 2:
        print("forge report duplicates: --min-copies must be >= 2", file=sys.stderr)
        return 2
    try:
        engine = get_engine()
        return run_report(engine, args)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
