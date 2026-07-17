from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Allow `python script/spark_curate` and `python -m spark_curate` from script/
_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from spark_curate.apply_moves import apply_decision  # noqa: E402
from spark_curate.config import CurateConfig, SparkConfig, load_config, save_example_config  # noqa: E402
from spark_curate.decide import decide_one  # noqa: E402
from spark_curate.walk import iter_model_folders  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Organize a Manyfold 3D-Prints library using DGX Spark "
            "(Gemma vision + Qwen curator + NudeNet). "
            "Never deletes; only rearranges. Default is dry-run."
        )
    )
    p.add_argument(
        "--library",
        default=None,
        help=r"Library root (default: \\192.168.11.102\Backups\3D-Prints)",
    )
    p.add_argument("--config", default=None, help="JSON config path")
    p.add_argument(
        "--write-example-config",
        metavar="PATH",
        help="Write example config JSON and exit",
    )
    p.add_argument("--apply", action="store_true", help="Perform moves (default: dry-run)")
    p.add_argument("--limit", type=int, default=0, help="Max model folders (0=all)")
    p.add_argument(
        "--category",
        action="append",
        dest="categories",
        default=[],
        help="Only process this top-level category (repeatable)",
    )
    p.add_argument("--workers", type=int, default=None, help="Parallel vision workers (default 2)")
    p.add_argument(
        "--min-confidence",
        type=float,
        default=None,
        help="Min confidence to auto-move (default 0.55)",
    )
    p.add_argument(
        "--skip-good",
        action="store_true",
        help="Skip folders that already have preview.jpg and are not under Unknown",
    )
    p.add_argument(
        "--smoke",
        action="store_true",
        help="Ping Spark endpoints and exit",
    )
    return p


def smoke(spark: SparkConfig) -> int:
    import urllib.request

    ok = 0
    for name, url in [
        ("gemma models", spark.gemma_url.rstrip("/") + "/models"),
        ("curator models", spark.curator_url.rstrip("/") + "/models"),
        ("nudenet health", spark.nudenet_url.rstrip("/") + "/health"),
    ]:
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                print(f"OK  {name}: HTTP {r.status}")
                ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {name}: {e}")
    return 0 if ok == 3 else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.write_example_config:
        path = Path(args.write_example_config)
        save_example_config(path)
        print(f"Wrote {path}")
        return 0

    spark, curate = load_config(args.config)
    if args.library:
        curate.library_root = args.library
    if args.limit:
        curate.limit = args.limit
    if args.categories:
        curate.only_categories = args.categories
    if args.workers is not None:
        curate.workers = max(1, args.workers)
    if args.min_confidence is not None:
        curate.min_confidence = args.min_confidence
    if args.skip_good:
        curate.skip_if_has_preview_and_known_category = True

    if args.smoke:
        return smoke(spark)

    work = curate.resolved_work_dir()
    work.mkdir(parents=True, exist_ok=True)
    thumb_cache = work / "thumbs"
    thumb_cache.mkdir(exist_ok=True)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    decisions_path = work / f"decisions-{run_id}.jsonl"
    audit_path = work / f"audit-{run_id}.jsonl"
    log_path = work / f"run-{run_id}.log"

    print(f"Library:  {curate.library_root}")
    print(f"Work dir: {work}")
    print(f"Mode:     {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"Min conf: {curate.min_confidence}")
    print(f"Workers:  {curate.workers}")

    folders = iter_model_folders(curate)
    print(f"Found {len(folders)} model folders")

    if curate.skip_if_has_preview_and_known_category:
        filtered = []
        for f in folders:
            preview = f.path / "preview.jpg"
            if preview.is_file() and f.category.lower() != "unknown":
                continue
            filtered.append(f)
        print(f"After --skip-good: {len(filtered)} folders")
        folders = filtered

    if not folders:
        print("Nothing to do.")
        return 0

    def job(folder):
        try:
            return decide_one(folder, spark, curate, thumb_cache)
        except Exception as e:  # noqa: BLE001
            from spark_curate.decide import Decision

            return Decision(
                source_path=str(folder.path),
                current_category=folder.category,
                current_name=folder.name,
                suggested_name=folder.name,
                category=folder.category,
                tags=[],
                has_usable_preview=False,
                content_type="other",
                is_junk=False,
                junk_reason=None,
                confidence=0.0,
                action="skip",
                notes="",
                sensitive=False,
                nudenet={},
                thumb_path=None,
                error=f"{e}\n{traceback.format_exc()[-500:]}",
            )

    decisions = []
    with ThreadPoolExecutor(max_workers=curate.workers) as ex:
        futs = {ex.submit(job, f): f for f in folders}
        done = 0
        for fut in as_completed(futs):
            d = fut.result()
            decisions.append(d)
            done += 1
            if done % 5 == 0 or done == len(folders):
                print(f"  decided {done}/{len(folders)} …", flush=True)

    # Stable order
    decisions.sort(key=lambda d: d.source_path.lower())

    with decisions_path.open("w", encoding="utf-8") as fh:
        for d in decisions:
            fh.write(json.dumps(d.to_dict(), ensure_ascii=False) + "\n")
    print(f"Wrote decisions: {decisions_path}")

    moved = kept = skipped = errors = 0
    with log_path.open("w", encoding="utf-8") as log_fh, audit_path.open(
        "w", encoding="utf-8"
    ) as audit_fh:
        log_fh.write(f"run={run_id} apply={args.apply}\n")
        for d in decisions:
            rec = apply_decision(curate, d, do_apply=args.apply, log_fh=log_fh)
            audit_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if rec.get("error") and not rec.get("applied"):
                errors += 1
            elif rec.get("applied") or (
                not args.apply and rec.get("dest") and not rec.get("skipped_reason")
            ):
                moved += 1
            elif rec.get("skipped_reason") in {None, "no_move_needed"} and rec.get("action") == "keep":
                kept += 1
            else:
                skipped += 1

    summary = {
        "run_id": run_id,
        "library": curate.library_root,
        "apply": args.apply,
        "folders": len(folders),
        "decisions": len(decisions),
        "moves_or_planned": moved,
        "kept": kept,
        "skipped": skipped,
        "errors": errors,
        "decisions_path": str(decisions_path),
        "audit_path": str(audit_path),
        "log_path": str(log_path),
    }
    summary_path = work / f"summary-{run_id}.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(
        "\nNext: review decisions JSONL, then re-run with --apply to rearrange.\n"
        "Then in Manyfold: Scan for new files / Detect filesystem changes."
    )
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
