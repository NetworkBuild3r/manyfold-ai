"""`forge packs resolve|sample|review|override` argument wiring (registered from forge.cli).

INIT-032/SPEC-010
"""

from __future__ import annotations

import argparse
import json
import sys


def register(sub: argparse._SubParsersAction) -> None:
    packs = sub.add_parser("packs", help="Pack resolution (SPEC-010)")
    ps = packs.add_subparsers(dest="packs_command", required=True)

    res = ps.add_parser("resolve", help="Resolve units into final packs (deterministic, then LLM)")
    res.add_argument("--dry-run", action="store_true", help="compute and report; write nothing")
    res.add_argument(
        "--no-llm",
        action="store_true",
        help="skip the LLM tier (in-band pairs stay separate, undecided, until a later run)",
    )
    res.add_argument("--llm-limit", type=int, default=None, metavar="N", help="max new LLM calls")
    res.add_argument("--commons-k", type=int, default=None, metavar="K")
    res.add_argument("--band-low", type=float, default=None)
    res.add_argument("--band-high", type=float, default=None)
    res.add_argument("--bundle-items", type=int, default=None)
    res.add_argument("--colocate", choices=("meshless", "all", "off"), default=None)
    res.add_argument("--concurrency", type=int, default=None, help="LLM calls in flight (max 4)")

    smp = ps.add_parser("sample", help="Print N random LLM decisions with evidence (JSONL)")
    smp.add_argument("--n", type=int, default=40)
    smp.add_argument("--seed", type=int, default=32)

    rev = ps.add_parser("review", help="Write the review CSV (unsure / low-confidence pairs)")
    rev.add_argument("--out", default="-", help="file path or - for stdout")

    ovr = ps.add_parser("override", help="Import human verdicts (CSV: key_a,key_b,verdict,note)")
    ovr.add_argument("--file", required=True)


def main(args: argparse.Namespace) -> int:
    from forge.config import ConfigError
    from forge.packs.llm import LlmConfigError

    try:
        if args.packs_command == "resolve":
            return _resolve(args)
        if args.packs_command == "sample":
            from forge.packs.review import sample

            sample(args.n, seed=args.seed)
            return 0
        if args.packs_command == "review":
            from forge.packs.review import export_review

            if args.out == "-":
                n = export_review(sys.stdout)
            else:
                with open(args.out, "w", newline="", encoding="utf-8") as fh:
                    n = export_review(fh)
            print(f"review rows: {n}", file=sys.stderr)
            return 0
        if args.packs_command == "override":
            from forge.packs.review import OverrideError, import_csv

            try:
                print(json.dumps(import_csv(args.file)))
            except OverrideError as exc:
                print(f"forge packs override: {exc}", file=sys.stderr)
                return 2
            return 0
    except (ConfigError, LlmConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"forge packs: unknown command {args.packs_command}", file=sys.stderr)
    return 2


def _resolve(args: argparse.Namespace) -> int:
    from forge.packs.resolve import ResolveBusy, run
    from forge.packs.settings import PacksSettings

    settings = PacksSettings.from_env().with_overrides(
        commons_k=args.commons_k,
        band_low=args.band_low,
        band_high=args.band_high,
        bundle_items=args.bundle_items,
        colocate=args.colocate,
        llm_concurrency=args.concurrency,
    )
    try:
        result = run(
            dry_run=args.dry_run,
            settings=settings,
            use_llm=not args.no_llm,
            llm_limit=args.llm_limit,
        )
    except ResolveBusy as exc:
        print(str(exc), file=sys.stderr)
        return 3
    print(json.dumps({"dry_run": result.dry_run, **result.counts}, indent=2))
    return 0
