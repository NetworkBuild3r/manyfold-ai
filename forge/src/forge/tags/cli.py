"""`forge tags [--dry-run] | sample | stats | review | override` wiring (registered from forge.cli).

INIT-032/SPEC-016
"""

from __future__ import annotations

import argparse
import json
import sys


def register(sub: argparse._SubParsersAction) -> None:
    tags = sub.add_parser("tags", help="Searchable tags per pack (SPEC-016)")
    tags.add_argument("--dry-run", action="store_true", help="compute and report; write nothing")
    tags.add_argument("--no-llm", action="store_true", help="code-derived + classify tags only")
    tags.add_argument(
        "--llm-limit", type=int, default=None, metavar="N", help="at most N LLM calls"
    )
    tags.add_argument("--concurrency", type=int, default=4, help="LLM calls in flight (max 4)")
    tags.add_argument(
        "--pack", type=int, action="append", dest="packs", metavar="ID", help="only this pack id"
    )
    tags.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="at most N packs (packs in the active materialize plan first, then by id)",
    )
    ts = tags.add_subparsers(dest="tags_command", required=False)
    smp = ts.add_parser("sample", help="Print N random tagged packs (JSONL)")
    smp.add_argument("--n", type=int, default=20)
    smp.add_argument("--seed", type=int, default=32)
    st = ts.add_parser("stats", help="Tag coverage and the most common tags (JSON)")
    st.add_argument("--top", type=int, default=30)
    rev = ts.add_parser("review", help="Write the tag review CSV")
    rev.add_argument("--out", default="-")
    rev.add_argument("--pack", type=int, action="append", dest="review_packs", metavar="ID")
    ovr = ts.add_parser("override", help="Import human tag overrides (CSV)")
    ovr.add_argument("--file", required=True)


def main(args: argparse.Namespace) -> int:
    from forge.config import ConfigError
    from forge.packs.llm import LlmConfigError

    cmd = getattr(args, "tags_command", None)
    try:
        if cmd == "sample":
            from forge.tags.review import sample

            sample(args.n, seed=args.seed)
            return 0
        if cmd == "stats":
            from forge.tags.review import stats

            print(json.dumps(stats(top=args.top), indent=2, ensure_ascii=False))
            return 0
        if cmd == "review":
            from forge.tags.review import export_review

            if args.out == "-":
                n = export_review(sys.stdout, pack_ids=args.review_packs)
            else:
                with open(args.out, "w", newline="", encoding="utf-8") as fh:
                    n = export_review(fh, pack_ids=args.review_packs)
            print(f"review rows: {n}", file=sys.stderr)
            return 0
        if cmd == "override":
            from forge.tags.review import TagOverrideError, import_csv

            try:
                print(json.dumps(import_csv(args.file)))
            except TagOverrideError as exc:
                print(f"forge tags override: {exc}", file=sys.stderr)
                return 2
            return 0
        from forge.packs.resolve import ResolveBusy
        from forge.tags.run import run

        try:
            result = run(
                dry_run=args.dry_run,
                use_llm=not args.no_llm,
                llm_limit=args.llm_limit,
                concurrency=args.concurrency,
                pack_ids=args.packs,
                limit=args.limit,
            )
        except ResolveBusy as exc:
            print(str(exc), file=sys.stderr)
            return 3
        print(
            json.dumps(
                {
                    "dry_run": result.dry_run,
                    "model": result.model,
                    **result.counts,
                    "top_tags": [[t, n] for t, n in result.top_tags[:20]],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    except (ConfigError, LlmConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
