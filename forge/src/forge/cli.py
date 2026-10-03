"""Library Forge CLI. Stubs print 'not implemented' and exit 2.

Real: `db`, `walk`, `sweep`, `status`, `report`.

Other specs add logic via modules (forge.walker.run, forge.sweep.run, …)
without growing this file into a router.

INIT-032/SPEC-004 · walk wired by SPEC-005 · sweep/status by SPEC-007
· report wired by SPEC-009 · report site by SPEC-014
"""

from __future__ import annotations

import argparse
import sys

from forge import __version__

_STUBS = (
    "packs",
    "classify",
)


def _not_implemented(name: str) -> int:
    print(f"forge {name}: not implemented", file=sys.stderr)
    return 2


def _add_stub(sub: argparse._SubParsersAction, name: str, help_text: str) -> None:
    sub.add_parser(name, help=help_text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forge",
        description="Library Forge — catalog and materialize the 3D-print library",
    )
    parser.add_argument("--version", action="version", version=f"forge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    walk = sub.add_parser("walk", help="Inventory the source root (SPEC-005)")
    walk.add_argument(
        "--dry-run",
        action="store_true",
        help="Count only; never write the database (safe on a read-only mount)",
    )
    walk.add_argument(
        "--threads",
        type=int,
        default=8,
        metavar="N",
        help="os.scandir worker threads (default 8)",
    )
    sweep = sub.add_parser("sweep", help="Claim and process pending containers (SPEC-007)")
    sweep.add_argument(
        "--worker",
        action="store_true",
        help="Run sweep worker processes (claim -> engine -> catalog)",
    )
    sweep.add_argument(
        "--procs",
        type=int,
        default=8,
        metavar="N",
        help="worker processes, each with its own DB connection (default 8)",
    )
    sweep.add_argument(
        "--once",
        action="store_true",
        help="exit when no pending or claimed containers remain instead of polling",
    )
    sweep.add_argument(
        "--metrics-port",
        type=int,
        default=None,
        metavar="PORT",
        help="serve Prometheus /metrics on this port (e.g. 9100)",
    )
    sweep.add_argument(
        "--worker-id",
        default=None,
        help="worker id prefix (default $FORGE_WORKER_ID, else the hostname)",
    )
    status = sub.add_parser("status", help="Print sweep progress (containers, failures, rate, ETA)")
    status.add_argument("--json", action="store_true", help="machine-readable output")
    report = sub.add_parser("report", help="Inventory and duplicate reports (SPEC-009)")
    report_sub = report.add_subparsers(dest="report_command", required=True)
    inv = report_sub.add_parser("inventory", help="What the catalog actually holds")
    dups = report_sub.add_parser("duplicates", help="Cross-pack mesh duplicates")
    for p in (inv, dups):
        p.add_argument(
            "--format",
            choices=("json", "csv", "md"),
            default="json",
            help="output format (default json)",
        )
        p.add_argument(
            "--out",
            metavar="DIR",
            help="write report file(s) into DIR (stdout if omitted)",
        )
    dups.add_argument(
        "--min-copies",
        type=int,
        default=2,
        metavar="N",
        help="list mesh blobs occurring in >= N distinct packs (default 2)",
    )
    dups.add_argument(
        "--limit",
        type=int,
        default=500,
        metavar="N",
        help="max blob and pair rows (default 500; 0 = no cap)",
    )
    site = report_sub.add_parser("site", help="Static HTML from JSON reports (SPEC-014)")
    site.add_argument(
        "--in",
        dest="in_dir",
        required=True,
        metavar="DIR",
        help="directory containing inventory.json and/or duplicates.json",
    )
    site.add_argument(
        "--out",
        dest="out_dir",
        required=True,
        metavar="DIR",
        help="directory to write HTML, assets, and chunked pair JSON",
    )
    _add_stub(sub, "packs", "Pack resolution (SPEC-010)")
    _add_stub(sub, "classify", "Category / name / creator (SPEC-011)")
    from forge.materialize.cli import add_parser as _add_materialize

    _add_materialize(sub)

    db = sub.add_parser("db", help="Alembic wrappers (upgrade / downgrade / current)")
    db_sub = db.add_subparsers(dest="db_command", required=True)
    upgrade = db_sub.add_parser("upgrade", help="alembic upgrade (default: head)")
    upgrade.add_argument("revision", nargs="?", default="head")
    downgrade = db_sub.add_parser("downgrade", help="alembic downgrade REVISION")
    downgrade.add_argument("revision")
    db_sub.add_parser("current", help="print the current alembic revision")
    return parser


def _cmd_walk(args: argparse.Namespace) -> int:
    from forge.config import ConfigError
    from forge.walker import format_counts, run

    try:
        result = run(dry_run=args.dry_run, threads=args.threads)
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(format_counts(result.counts))
    return 0


def _cmd_sweep(args: argparse.Namespace) -> int:
    if not args.worker:
        print("forge sweep: pass --worker to run sweep workers", file=sys.stderr)
        return 2
    if args.procs < 1:
        print("forge sweep: --procs must be >= 1", file=sys.stderr)
        return 2
    from forge.sweep import main_sweep

    return main_sweep(
        procs=args.procs,
        once=args.once,
        metrics_port=args.metrics_port,
        worker_id=args.worker_id,
    )


def _cmd_status(args: argparse.Namespace) -> int:
    from forge.status import main_status

    return main_status(as_json=args.json)


def _cmd_report(args: argparse.Namespace) -> int:
    if args.report_command == "site":
        from forge.site.cli import main_site

        return main_site(args)
    from forge.reports.cli import main_report

    return main_report(args)


def _cmd_db(args: argparse.Namespace) -> int:
    from forge.config import ConfigError
    from forge.db import migrate

    try:
        if args.db_command == "upgrade":
            migrate.upgrade(args.revision)
        elif args.db_command == "downgrade":
            migrate.downgrade(args.revision)
        elif args.db_command == "current":
            migrate.current()
        else:
            return _not_implemented(f"db {args.db_command}")
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "walk":
        return _cmd_walk(args)
    if args.command == "sweep":
        return _cmd_sweep(args)
    if args.command == "status":
        return _cmd_status(args)
    if args.command == "report":
        return _cmd_report(args)
    if args.command == "materialize":
        from forge.materialize.cli import main as materialize_main

        return materialize_main(args)
    if args.command in _STUBS:
        return _not_implemented(args.command)
    if args.command == "db":
        return _cmd_db(args)
    return _not_implemented(args.command)


def _entry() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    _entry()
