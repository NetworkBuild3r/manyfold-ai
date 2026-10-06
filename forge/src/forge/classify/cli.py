"""`forge classify [--dry-run] | sample | review | override` wiring (registered from forge.cli).

INIT-032/SPEC-011
"""

from __future__ import annotations

import argparse
import json
import sys


def register(sub: argparse._SubParsersAction) -> None:
    cls = sub.add_parser("classify", help="Category / name / creator (SPEC-011)")
    cls.add_argument("--dry-run", action="store_true", help="compute and report; write nothing")
    cls.add_argument("--no-llm", action="store_true", help="LLM-needing packs -> Misc (deferred)")
    cls.add_argument("--llm-limit", type=int, default=None, metavar="N")
    cls.add_argument("--min-confidence", type=float, default=None)
    cls.add_argument("--concurrency", type=int, default=4, help="LLM calls in flight (max 4)")
    cls.add_argument(
        "--source-root",
        default=None,
        help="read-only library root for datapackage.json (default $FORGE_SOURCE_ROOT)",
    )
    cs = cls.add_subparsers(dest="classify_command", required=False)
    smp = cs.add_parser("sample", help="Print N random classifications with evidence (JSONL)")
    smp.add_argument("--n", type=int, default=50)
    smp.add_argument("--seed", type=int, default=32)
    rev = cs.add_parser("review", help="Write the classification review CSV")
    rev.add_argument("--out", default="-")
    ovr = cs.add_parser("override", help="Import human classification overrides (CSV)")
    ovr.add_argument("--file", required=True)


def main(args: argparse.Namespace) -> int:
    from forge.config import ConfigError
    from forge.packs.llm import LlmConfigError

    cmd = getattr(args, "classify_command", None)
    try:
        if cmd == "sample":
            from forge.classify.review import sample

            sample(args.n, seed=args.seed)
            return 0
        if cmd == "review":
            from forge.classify.review import export_review

            if args.out == "-":
                n = export_review(sys.stdout)
            else:
                with open(args.out, "w", newline="", encoding="utf-8") as fh:
                    n = export_review(fh)
            print(f"review rows: {n}", file=sys.stderr)
            return 0
        if cmd == "override":
            from forge.classify.review import ClassifyOverrideError, import_csv

            try:
                print(json.dumps(import_csv(args.file)))
            except ClassifyOverrideError as exc:
                print(f"forge classify override: {exc}", file=sys.stderr)
                return 2
            return 0
        from forge.classify.run import DEFAULT_MIN_CONFIDENCE, run
        from forge.packs.resolve import ResolveBusy

        try:
            result = run(
                dry_run=args.dry_run,
                use_llm=not args.no_llm,
                llm_limit=args.llm_limit,
                source_root=args.source_root,
                min_confidence=args.min_confidence or DEFAULT_MIN_CONFIDENCE,
                concurrency=args.concurrency,
            )
        except ResolveBusy as exc:
            print(str(exc), file=sys.stderr)
            return 3
        print(json.dumps({"dry_run": result.dry_run, **result.counts}, indent=2))
        return 0
    except (ConfigError, LlmConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
