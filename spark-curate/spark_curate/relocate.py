"""In-library dump relocate planner + gated apply (INIT-025/SPEC-003).

Walks **one** named library dest (a dump **bucket**, not a pack), plans pack-root
lifts to depth-2 ``Category/Pack``, and applies only listed ``lift`` rows when
``APPLY=1``. Default is dry-run (``APPLY=0``). Never deletes NFS. Never suffixes
``Name (N)``. Collision is ``hold``. Sibling dump dests are inventoried only.

This lane is not Unorg ``MODE=unorganize`` and does not emit ``new|attach|hold``
promote verdicts (ADR D-2).

JSONL artifacts (under library ``.spark-curate/``)::

    relocate-plan-{run_id}.jsonl
        kind=lift     source (abs) → dest (Category/Pack, depth 2)
        kind=hold     intended dest already exists; no move
        kind=leftover dest-root files that stay at the namesake folder
    relocate-siblings-{run_id}.jsonl
        kind=sibling_dump  other organize-applied dump dests; move=false
    relocate-summary-{run_id}.json

Each plan line includes ``provenance``, ``category``, and ``category_source``
(``dest_parent`` — first segment of the named dest; AnySTL fallback is that
parent when dest is ``AnySTL/…``).

Pack-root grain reuses INIT-021 D-2 (``COMMON_SUBFOLDERS``,
``_folder_bears_indexable``) — the set is not widened. The dest folder itself
is never a pack even when leftover files sit at its root. Nested drawers such
as ``18+ 45GB`` that do not bear indexable at their own level are buckets;
inner pack roots lift.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import CurateConfig
from .indexable import COMMON_SUBFOLDERS, should_skip_dir_name
from .pathsafe import (
    PathUnsafeError,
    assert_jailed_destination,
    check_rel_path,
)
from .unorganize import (
    FrozenRootWriteRefused,
    _folder_bears_indexable,
    _iter_dir_entries,
    _scan_name_safe,
    _under,
    assert_intake_contained,
    assert_writable_work_dir,
)

log = logging.getLogger(__name__)

PROVENANCE = "INIT-025/SPEC-003"
PRIMARY_DEST = "AnySTL/Girl Sitting on Dinosaur"
CATEGORY_SOURCE_DEST_PARENT = "dest_parent"

# Organize-applied dump sources (RSCH-009 / ADR D-6). Inventory only.
_DUMP_SOURCE_HINT = re.compile(r"ANYSTL\s+-|NSFW", re.I)
_DRIVE_ABS_RE = re.compile(r"^[A-Za-z]:[\\/]")


class RelocateError(Exception):
    """Base for relocate-lane failures."""


class DestJailRefused(RelocateError):
    """Dest empty, ``.``, absolute, ``..``, Unorg/Mega, or outside the library."""


class LibraryRootError(RelocateError):
    """Library root missing or not a directory."""


class RelocateApplyError(RelocateError):
    """A gated apply move was refused (jail / collision / missing source)."""


def _refuse_unorg_or_mega(path: Path) -> None:
    text = str(path)
    if "3D-Prints-Unorg" in text or "/intake/Mega" in text:
        raise DestJailRefused("Mega / Unorg dest refused")


def validate_dest(library_root: Path, dest: str | None) -> Path:
    """Fail loud on dest jail violations (REQ-005). Does not coerce to ``.``."""
    if dest is None:
        raise DestJailRefused("dest is required")
    if not isinstance(dest, str):
        raise DestJailRefused("dest must be a str")
    raw = dest.strip()
    if raw == "":
        raise DestJailRefused("empty dest refused")
    if raw in {".", "./"}:
        raise DestJailRefused(
            "dest '.' refused — would organize-APPLY the library"
        )
    if raw == "/":
        raise DestJailRefused("dest '/' refused")
    if raw.startswith("/") or Path(raw).is_absolute() or _DRIVE_ABS_RE.match(raw):
        raise DestJailRefused("absolute dest refused")
    if raw.startswith("\\\\"):
        raise DestJailRefused("UNC dest refused")
    try:
        category, name = check_rel_path(raw)
    except PathUnsafeError as e:
        raise DestJailRefused(str(e)) from e

    if not library_root.is_dir():
        raise LibraryRootError(f"Library root not found: {library_root}")
    lib = library_root.resolve()
    _refuse_unorg_or_mega(lib)
    dest_path = lib / category / name
    _refuse_unorg_or_mega(dest_path)
    try:
        assert_jailed_destination(dest_path, lib)
    except PathUnsafeError as e:
        raise DestJailRefused(str(e)) from e
    if dest_path.resolve() == lib:
        raise DestJailRefused("dest resolves to library root")
    if not _under(dest_path.resolve(), lib) or dest_path.resolve() == lib:
        raise DestJailRefused("dest outside library root")
    return dest_path


def _category_from_dest(dest_rel: str) -> str:
    category, _name = check_rel_path(dest_rel)
    return category


def collect_relocate_pack_roots(
    dest_path: Path, library_root: Path
) -> list[tuple[Path, list[str], list[Path]]]:
    """Shallowest pack roots under *dest_path* (dest itself is never a pack).

    INIT-021 D-2 grain: a folder that bears indexable files directly or only via
    ``COMMON_SUBFOLDERS`` is a pack; descent stops so inner assets stay with it.
    A child that does not bear indexable (e.g. ``18+ 45GB``) is a nested bucket
    and is walked for inner pack roots.
    """
    found: list[tuple[Path, list[str], list[Path]]] = []

    def walk(folder: Path, *, is_dest: bool) -> None:
        assert_intake_contained(folder, library_root)
        if should_skip_dir_name(folder.name) and not is_dest:
            return
        if not is_dest and folder.name.lower() in COMMON_SUBFOLDERS:
            return
        if not is_dest:
            bears, signals, archives = _folder_bears_indexable(
                folder, library_root
            )
            if bears:
                found.append((folder, signals, archives))
                return
        for entry in _iter_dir_entries(folder):
            if not entry.is_dir(follow_symlinks=False):
                continue
            if should_skip_dir_name(entry.name):
                continue
            if entry.name.lower() in COMMON_SUBFOLDERS:
                continue
            walk(Path(entry.path), is_dest=False)

    walk(dest_path, is_dest=True)
    return found


def _leftover_dest_files(dest_path: Path, pack_roots: list[Path]) -> list[str]:
    """Namesake leftover files at the dest folder (ADR D-8). Not deleted."""
    pack_resolved = {p.resolve() for p in pack_roots}
    leftover: list[str] = []
    for entry in _iter_dir_entries(dest_path):
        _scan_name_safe(entry.name)
        if entry.is_file(follow_symlinks=False):
            leftover.append(entry.name)
            continue
        if not entry.is_dir(follow_symlinks=False):
            continue
        child = Path(entry.path).resolve()
        if child in pack_resolved:
            continue
        # Nested bucket (contains packs) stays in place; not dest leftover.
        if any(_under(p, child) for p in pack_resolved):
            continue
    leftover.sort(key=str.lower)
    return leftover


def _plan_row(
    *,
    kind: str,
    source: str,
    dest: str | None,
    category: str,
    pack_name: str | None,
    status: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "provenance": PROVENANCE,
        "kind": kind,
        "source": source,
        "dest": dest,
        "category": category,
        "category_source": CATEGORY_SOURCE_DEST_PARENT,
        "pack_name": pack_name,
        "status": status,
    }
    if extra:
        row.update(extra)
    return row


def _inventory_siblings(
    library_root: Path, current_dest_rel: str
) -> list[dict[str, Any]]:
    """Organize-applied dump dests from audit JSONL (ADR D-6). Never moves."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    spark = library_root / ".spark-curate"
    if not spark.is_dir():
        return rows
    for path in sorted(spark.glob("audit-*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            log.warning("cannot read sibling audit %s: %s", path.name, e)
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not rec.get("applied"):
                continue
            source = str(rec.get("source") or "")
            dest_raw = str(rec.get("dest") or "")
            if not dest_raw:
                continue
            if not (
                _DUMP_SOURCE_HINT.search(source) or _DUMP_SOURCE_HINT.search(dest_raw)
            ):
                continue
            dest_rel = _rel_under_library(library_root, dest_raw)
            if dest_rel is None or dest_rel == current_dest_rel:
                continue
            if dest_rel in seen:
                continue
            seen.add(dest_rel)
            rows.append(
                {
                    "provenance": PROVENANCE,
                    "kind": "sibling_dump",
                    "dest": dest_rel,
                    "source_audit": source,
                    "audit_file": path.name,
                    "move": False,
                    "status": "inventory",
                }
            )
    return rows


def _rel_under_library(library_root: Path, dest_raw: str) -> str | None:
    try:
        p = Path(dest_raw)
        lib = library_root.resolve()
        if p.is_absolute():
            rel = p.resolve().relative_to(lib)
        else:
            rel = Path(str(dest_raw).replace("\\", "/"))
        posix = rel.as_posix()
        if not posix or posix == ".":
            return None
        check_rel_path(posix)
        return posix
    except (ValueError, PathUnsafeError, OSError):
        return None


def _collision_exists(library_root: Path, dest_rel: str, source: Path) -> bool:
    dest_path = library_root / dest_rel
    if not dest_path.exists():
        return False
    try:
        return dest_path.resolve() != source.resolve()
    except OSError:
        return True


@dataclass
class RelocateResult:
    run_id: str
    library_root: str
    dest: str
    plans: list[dict[str, Any]]
    siblings: list[dict[str, Any]]
    plan_path: Path
    siblings_path: Path
    summary_path: Path
    applied: int = 0
    errors: list[str] = field(default_factory=list)

    def summary_dict(self) -> dict[str, Any]:
        return {
            "provenance": PROVENANCE,
            "run_id": self.run_id,
            "library_root": self.library_root,
            "dest": self.dest,
            "lift": sum(1 for p in self.plans if p.get("kind") == "lift"),
            "hold": sum(1 for p in self.plans if p.get("kind") == "hold"),
            "leftover": sum(1 for p in self.plans if p.get("kind") == "leftover"),
            "siblings": len(self.siblings),
            "applied": self.applied,
            "plan_path": str(self.plan_path),
            "siblings_path": str(self.siblings_path),
            "summary_path": str(self.summary_path),
            "errors": self.errors,
        }


def plan_relocate(
    cfg: CurateConfig,
    dest: str,
    *,
    run_id: str | None = None,
) -> RelocateResult:
    """Walk the named dest and write relocate JSONL (no ``mv``)."""
    root = Path(cfg.library_root)
    dest_path = validate_dest(root, dest)
    if not dest_path.is_dir():
        raise DestJailRefused("dest is not a directory")
    lib = root.resolve()
    dest_resolved = dest_path.resolve()
    dest_rel = dest_resolved.relative_to(lib).as_posix()
    category = _category_from_dest(dest_rel)

    run_id = run_id or time.strftime("%Y%m%d-%H%M%S")
    work = Path(cfg.work_dir) if cfg.work_dir else lib / ".spark-curate"
    assert_writable_work_dir(work)
    work.mkdir(parents=True, exist_ok=True)

    pack_hits = collect_relocate_pack_roots(dest_resolved, lib)
    plans: list[dict[str, Any]] = []
    reserved: set[str] = set()

    for pack_path, signals, _archives in sorted(
        pack_hits, key=lambda t: str(t[0]).lower()
    ):
        pack_name = pack_path.name
        dest_rel_pack = f"{category}/{pack_name}"
        try:
            check_rel_path(dest_rel_pack)
        except PathUnsafeError:
            plans.append(
                _plan_row(
                    kind="hold",
                    source=str(pack_path.resolve()),
                    dest=None,
                    category=category,
                    pack_name=pack_name,
                    status="hold",
                    extra={
                        "reason": "unsafe_destination",
                        "signals": sorted(signals),
                    },
                )
            )
            continue
        collision = (
            _collision_exists(lib, dest_rel_pack, pack_path)
            or dest_rel_pack in reserved
        )
        if collision:
            plans.append(
                _plan_row(
                    kind="hold",
                    source=str(pack_path.resolve()),
                    dest=dest_rel_pack,
                    category=category,
                    pack_name=pack_name,
                    status="hold",
                    extra={
                        "reason": "collision",
                        "signals": sorted(signals),
                    },
                )
            )
            continue
        reserved.add(dest_rel_pack)
        plans.append(
            _plan_row(
                kind="lift",
                source=str(pack_path.resolve()),
                dest=dest_rel_pack,
                category=category,
                pack_name=pack_name,
                status="lift",
                extra={"signals": sorted(signals)},
            )
        )

    leftover = _leftover_dest_files(dest_resolved, [p[0] for p in pack_hits])
    plans.append(
        _plan_row(
            kind="leftover",
            source=str(dest_resolved),
            dest=dest_rel,
            category=category,
            pack_name=dest_resolved.name,
            status="leftover",
            extra={"leftover_files": leftover},
        )
    )

    siblings = _inventory_siblings(lib, dest_rel)

    plan_path = work / f"relocate-plan-{run_id}.jsonl"
    siblings_path = work / f"relocate-siblings-{run_id}.jsonl"
    summary_path = work / f"relocate-summary-{run_id}.json"

    with plan_path.open("w", encoding="utf-8") as fh:
        for row in plans:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    with siblings_path.open("w", encoding="utf-8") as fh:
        for row in siblings:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    result = RelocateResult(
        run_id=run_id,
        library_root=str(lib),
        dest=dest_rel,
        plans=plans,
        siblings=siblings,
        plan_path=plan_path,
        siblings_path=siblings_path,
        summary_path=summary_path,
    )
    summary_path.write_text(
        json.dumps(result.summary_dict(), indent=2), encoding="utf-8"
    )
    log.info(
        "relocate plan dest=%s lift=%s hold=%s leftover=%s siblings=%s apply=0",
        dest_rel,
        result.summary_dict()["lift"],
        result.summary_dict()["hold"],
        result.summary_dict()["leftover"],
        len(siblings),
    )
    return result


def apply_relocate(
    cfg: CurateConfig,
    result: RelocateResult,
    *,
    dest: str,
) -> RelocateResult:
    """``mv`` only ``kind=lift`` rows jailed under the named dest. Never delete.

    Intended for SPEC-004's gated Job. This spec's unattended run uses APPLY=0.
    """
    root = Path(cfg.library_root).resolve()
    dest_path = validate_dest(root, dest).resolve()
    applied = 0
    errors = list(result.errors)

    for row in result.plans:
        if row.get("kind") != "lift":
            continue
        src = Path(str(row["source"]))
        dest_rel = str(row.get("dest") or "")
        try:
            if not src.is_dir():
                raise RelocateApplyError("source missing")
            src_r = src.resolve()
            if not _under(src_r, dest_path) or src_r == dest_path:
                raise RelocateApplyError("source escapes dest jail")
            check_rel_path(dest_rel)
            dest_abs = assert_jailed_destination(root / dest_rel, root)
            if dest_abs.exists():
                raise RelocateApplyError("dest exists — hold, never Name (N)")
            dest_abs.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src_r), str(dest_abs))
            row["applied"] = True
            applied += 1
            log.info("relocate MOVE %s -> %s", src_r, dest_rel)
        except (RelocateApplyError, PathUnsafeError, OSError) as e:
            row["applied"] = False
            row["error"] = type(e).__name__
            errors.append(f"{src.name}: {type(e).__name__}")
            log.warning("relocate apply refused %s: %s", src.name, type(e).__name__)

    result.applied = applied
    result.errors = errors
    result.summary_path.write_text(
        json.dumps(result.summary_dict(), indent=2), encoding="utf-8"
    )
    return result


def run_relocate(
    cfg: CurateConfig,
    dest: str,
    *,
    do_apply: bool = False,
    run_id: str | None = None,
) -> RelocateResult:
    """Plan always; ``mv`` only when *do_apply* is true (default false)."""
    result = plan_relocate(cfg, dest, run_id=run_id)
    if do_apply:
        result = apply_relocate(cfg, result, dest=dest)
    return result


def run_relocate_cli(args, cfg: CurateConfig) -> int:
    """CLI entry for MODE=relocate. Default dry-run."""
    dest = getattr(args, "dest", None)
    do_apply = bool(getattr(args, "apply", False))
    print(f"Library:  {cfg.library_root}")
    print(f"Dest:     {dest!r}")
    print(f"Mode:     relocate {'APPLY' if do_apply else 'DRY-RUN (APPLY=0)'}")
    try:
        result = run_relocate(cfg, dest, do_apply=do_apply)
    except (DestJailRefused, LibraryRootError, FrozenRootWriteRefused) as e:
        print(f"ERROR: {type(e).__name__}: {e}")
        return 1
    print(json.dumps(result.summary_dict(), indent=2))
    print(
        f"\nWrote plan: {result.plan_path}\n"
        f"Wrote siblings: {result.siblings_path}\n"
        "Review relocate-plan JSONL before APPLY=1 (SPEC-004 Job)."
    )
    return 0 if not result.errors else 2
