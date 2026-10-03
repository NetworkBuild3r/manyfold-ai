"""Library Forge CLI. Stubs print 'not implemented' and exit 2; `db` is real.

Other specs add logic via modules (forge.walker.run, forge.sweep.run, …)
without growing this file into a router.

INIT-032/SPEC-004
"""

from __future__ import annotations

import argparse
import sys

from forge import __version__

_STUBS = (
    "walk",
    "sweep",
    "status",
    "report",
    "packs",
    "classify",
    "materialize",
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

    _add_stub(sub, "walk", "Inventory the source root (SPEC-005)")
    _add_stub(sub, "sweep", "Claim and process pending containers (SPEC-007)")
    _add_stub(sub, "status", "Print sweep progress")
    _add_stub(sub, "report", "Inventory and duplicate reports (SPEC-009)")
    _add_stub(sub, "packs", "Pack resolution (SPEC-010)")
    _add_stub(sub, "classify", "Category / name / creator (SPEC-011)")
    _add_stub(sub, "materialize", "Write the derived v2 tree (SPEC-012)")

    db = sub.add_parser("db", help="Alembic wrappers (upgrade / downgrade / current)")
    db_sub = db.add_subparsers(dest="db_command", required=True)
    upgrade = db_sub.add_parser("upgrade", help="alembic upgrade (default: head)")
    upgrade.add_argument("revision", nargs="?", default="head")
    downgrade = db_sub.add_parser("downgrade", help="alembic downgrade REVISION")
    downgrade.add_argument("revision")
    db_sub.add_parser("current", help="print the current alembic revision")
    return parser


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
    if args.command in _STUBS:
        return _not_implemented(args.command)
    if args.command == "db":
        return _cmd_db(args)
    return _not_implemented(args.command)


def _entry() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    _entry()
