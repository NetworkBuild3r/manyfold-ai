"""``forge materialize {plan,apply,status,verify,preflight,audit-source,gc-plan}`` wiring."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def add_parser(sub: argparse._SubParsersAction) -> None:
    m = sub.add_parser("materialize", help="Write the derived v2 tree (SPEC-012)")
    msub = m.add_subparsers(dest="mat_command", required=True)

    plan = msub.add_parser("plan", help="Decide the v2 tree from the catalog (DB only)")
    plan.add_argument("--layout", choices=("tree", "flat"), default="tree")
    plan.add_argument(
        "--include-provisional",
        action="store_true",
        help="also plan packs still in status 'provisional' (testing)",
    )
    plan.add_argument(
        "--pack",
        type=int,
        action="append",
        dest="packs",
        metavar="ID",
        help="plan only these pack ids (repeatable)",
    )
    plan.add_argument(
        "--out",
        metavar="PATH",
        help="write the plan as JSONL ('-' = stdout; files only under "
        "$FORGE_V2_ROOT or $FORGE_SCRATCH)",
    )
    plan.add_argument(
        "--force",
        action="store_true",
        help="supersede the active plan even while an apply holds claims",
    )

    apply = msub.add_parser("apply", help="Execute the active plan (resume-safe, idempotent)")
    g = apply.add_mutually_exclusive_group()
    g.add_argument("--pack", type=int, action="append", dest="packs", metavar="ID")
    g.add_argument("--limit", type=int, metavar="N", help="at most N not-yet-done packs")
    apply.add_argument(
        "--resume",
        action="store_true",
        help="treat every existing claim as dead (only when no other apply runs)",
    )
    apply.add_argument(
        "--retry-failed",
        action="store_true",
        help="reset failed units/blobs and failed/incomplete packs to pending",
    )
    apply.add_argument(
        "--procs", type=int, default=1, metavar="N", help="worker processes in this pod (default 1)"
    )
    apply.add_argument(
        "--io-mbps",
        type=float,
        default=None,
        metavar="MBPS",
        help="per-pod read/write budget in MB/s (default unlimited)",
    )
    apply.add_argument(
        "--no-copy-fallback",
        action="store_true",
        help="fail instead of copying when a hardlink is refused",
    )
    apply.add_argument(
        "--verify-loose",
        action="store_true",
        help="re-hash loose blobs after linking (reads every loose byte)",
    )
    apply.add_argument("--plan", type=int, default=None, metavar="ID")
    apply.add_argument("--worker-id", default=None)

    verify = msub.add_parser("verify", help="Check the v2 tree against the plan")
    vg = verify.add_mutually_exclusive_group()
    vg.add_argument(
        "--sample", type=int, default=100, metavar="N", help="hash N random inodes (default 100)"
    )
    vg.add_argument("--all", action="store_true", help="hash every inode")
    verify.add_argument("--plan", type=int, default=None, metavar="ID")
    verify.add_argument("--seed", type=int, default=None)
    verify.add_argument("--no-strays", action="store_true", help="skip the v2 stray walk")
    verify.add_argument(
        "--tree-hash",
        action="store_true",
        help="also print a deterministic digest of the whole v2 tree",
    )

    st = msub.add_parser("status", help="progress of the active (or given) plan")
    st.add_argument("--plan", type=int, default=None, metavar="ID")

    pre = msub.add_parser(
        "preflight",
        help="go/no-go: mount layout, free space, real source->v2 hardlink probes",
    )
    pre.add_argument(
        "--sample",
        type=int,
        default=20,
        metavar="N",
        help="random loose source files to probe (default 20)",
    )

    audit = msub.add_parser(
        "audit-source", help="stat catalog source files; report missing/changed (read-only)"
    )
    audit.add_argument("--sample", type=int, default=None, metavar="N")

    gc = msub.add_parser(
        "gc-plan", help="List v2 entries not in the plan (never deletes unless --apply-gc)"
    )
    gc.add_argument("--plan", type=int, default=None, metavar="ID")
    gc.add_argument(
        "--apply-gc", action="store_true", help="DELETE the listed entries (under v2 only)"
    )


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True, default=str))


def _guard_from_env(require_scratch: bool = False):
    from forge.config import optional_env

    from .guard import open_guard

    v2, src = optional_env("FORGE_V2_ROOT"), optional_env("FORGE_SOURCE_ROOT")
    scratch = optional_env("FORGE_SCRATCH")
    if not v2 or not src or (require_scratch and not scratch):
        from forge.config import ConfigError

        raise ConfigError("FORGE_V2_ROOT and FORGE_SOURCE_ROOT (and FORGE_SCRATCH) are required")
    return open_guard(
        v2, src, scratch, shared_mount_ack=optional_env("FORGE_SOURCE_SHARED_MOUNT") == "1"
    )


def _write_out(path: str, lines) -> None:
    if path == "-":
        for line in lines:
            print(line)
        return
    from .guard import GuardError
    from .store import TempWriter

    guard, _ = _guard_from_env()
    area = "v2"
    try:
        guard.check(path, "v2")
    except GuardError:
        area = "scratch"
        guard.check(path, "scratch")
    guard.mkdirs(Path(path).parent, area)
    w = TempWriter(guard, guard.new_temp_name(Path(path).parent, ".forge-tmp-", area), area)
    try:
        for line in lines:
            w.write((line + "\n").encode())
        w.close()
    except BaseException:
        w.abort()
        raise
    guard.rename(w.path, path, area)


def main(args: argparse.Namespace) -> int:
    from forge.config import ConfigError, optional_env, require_db_url
    from forge.db import get_engine

    from .guard import GuardError, StartupError

    try:
        db_url = require_db_url()
        cmd = args.mat_command
        if cmd == "plan":
            from .plan import PlanError, PlanOptions, build_plan, free_bytes_of, jsonl_lines

            opts = PlanOptions(
                layout=args.layout,
                include_provisional=args.include_provisional,
                pack_ids=args.packs,
                free_bytes=free_bytes_of(optional_env("FORGE_V2_ROOT")),
                force=args.force,
            )
            try:
                result = build_plan(get_engine(db_url), opts)
            except PlanError as x:
                print(f"forge materialize plan: {x}", file=sys.stderr)
                return 2
            if args.out:
                _write_out(args.out, jsonl_lines(result))
            _print(result.totals)
            return 0
        if cmd == "apply":
            from .apply import ApplySettings, main_apply

            settings = ApplySettings.from_env(
                procs=args.procs,
                io_mbps=args.io_mbps,
                allow_copy=not args.no_copy_fallback,
                verify_loose=args.verify_loose or None,
            )
            return main_apply(
                settings,
                db_url,
                plan_id=args.plan,
                pack_ids=args.packs,
                limit=args.limit,
                resume=args.resume,
                retry_failed=args.retry_failed,
                worker_id=args.worker_id,
            )
        if cmd == "verify":
            from .apply import active_plan_id
            from .verify import tree_hash, verify

            v2 = optional_env("FORGE_V2_ROOT")
            if not v2:
                raise ConfigError("FORGE_V2_ROOT is required")
            engine = get_engine(db_url)
            report = verify(
                engine,
                args.plan or active_plan_id(engine),
                Path(v2),
                sample=None if args.all else args.sample,
                full=args.all,
                seed=args.seed,
                check_strays=not args.no_strays,
            )
            if args.tree_hash:
                report["tree_hash"] = tree_hash(Path(v2))
            _print(report)
            return 0 if report["ok"] else 1
        if cmd == "status":
            from .apply import active_plan_id
            from .verify import status

            engine = get_engine(db_url)
            _print(status(engine, args.plan or active_plan_id(engine)))
            return 0
        if cmd == "preflight":
            from .verify import preflight

            guard, report = _guard_from_env(require_scratch=True)
            out = preflight(
                get_engine(db_url),
                guard,
                Path(guard.source_root),
                report.to_dict(),
                sample=args.sample,
            )
            _print(out)
            return 0 if out["ok"] else 1
        if cmd == "audit-source":
            from .verify import audit_source

            src = optional_env("FORGE_SOURCE_ROOT")
            if not src:
                raise ConfigError("FORGE_SOURCE_ROOT is required")
            report = audit_source(get_engine(db_url), Path(src), sample=args.sample)
            _print(report)
            return 0 if report["ok"] else 1
        if cmd == "gc-plan":
            from .apply import active_plan_id
            from .verify import gc_plan

            guard, _ = _guard_from_env()
            engine = get_engine(db_url)
            report = gc_plan(
                engine, args.plan or active_plan_id(engine), guard, apply_gc=args.apply_gc
            )
            _print(report)
            return 0
    except (ConfigError, StartupError) as x:
        print(f"forge materialize: {x}", file=sys.stderr)
        return 2
    except GuardError as x:
        print(f"forge materialize: GUARD REFUSED: {x}", file=sys.stderr)
        return 3
    return 2
