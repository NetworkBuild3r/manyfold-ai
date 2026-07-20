"""Write merge plans and pending handoff for Manyfold ApplySparkMergePlanJob."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, TextIO

from .config import CurateConfig
from .decide_merge import MergeDecision


PENDING_NAME = "merges-pending.jsonl"


def _pending_path(work: Path) -> Path:
    return work / PENDING_NAME


def write_merge_plans(
    cfg: CurateConfig,
    decisions: list[MergeDecision],
    *,
    do_apply: bool,
    run_id: str,
    log_fh: TextIO | None = None,
) -> dict[str, Any]:
    """
    Always write merges-{run_id}.jsonl.
    When do_apply and approved_for_apply, append to merges-pending.jsonl for Manyfold.
    Never deletes library content.
    """
    work = cfg.resolved_work_dir()
    work.mkdir(parents=True, exist_ok=True)
    plans_path = work / f"merges-{run_id}.jsonl"
    pending = _pending_path(work)

    planned = 0
    queued = 0
    kept = 0
    errors = 0

    with plans_path.open("w", encoding="utf-8") as fh:
        for d in decisions:
            rec = d.to_dict()
            rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            rec["run_id"] = run_id
            # Paths Manyfold resolves: relative Category/Model
            rec["path_a"] = d.rel_a
            rec["path_b"] = d.rel_b
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            planned += 1

            if d.error:
                errors += 1
            if d.decision != "merge":
                kept += 1
                continue

            msg = (
                f"MERGE? conf={d.confidence:.2f} target={d.target} "
                f"{d.rel_a} <-> {d.rel_b} | {d.reason}"
            )
            if log_fh:
                log_fh.write(msg + "\n")

            if not do_apply:
                continue
            if not d.approved_for_apply:
                if log_fh:
                    log_fh.write(
                        f"  skip pending: confidence {d.confidence:.2f} "
                        f"< {cfg.min_merge_confidence}\n"
                    )
                continue

            pending_rec = {
                "ts": rec["ts"],
                "run_id": run_id,
                "path_a": d.rel_a,
                "path_b": d.rel_b,
                "target": d.target,
                "confidence": d.confidence,
                "reason": d.reason,
                "signals": d.signals,
            }
            with pending.open("a", encoding="utf-8") as pfh:
                pfh.write(json.dumps(pending_rec, ensure_ascii=False) + "\n")
            queued += 1
            if log_fh:
                log_fh.write(f"  queued pending -> {pending}\n")

    return {
        "plans_path": str(plans_path),
        "pending_path": str(pending),
        "planned": planned,
        "queued_for_manyfold": queued,
        "keep_separate": kept,
        "errors": errors,
        "apply": do_apply,
        "min_merge_confidence": cfg.min_merge_confidence,
    }
