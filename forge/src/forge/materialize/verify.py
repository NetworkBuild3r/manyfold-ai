"""``forge materialize verify | audit-source | gc-plan``.

* **verify** — every planned file exists, is the blob-store inode (hardlink mode) or an identical
  copy, link counts are consistent, sha256 matches (sampled or ``--all``, one hash per inode), and
  nothing outside the plan lives under v2.
* **audit-source** — stats every catalog source file (read-only) and reports paths missing or
  whose size/mtime differ from ``source_files``. Never opens a file.
* **gc-plan** — lists v2 entries not in the plan. Deletes only with ``--apply-gc``, and only
  under v2 (through the write guard).
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import random
import stat
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .guard import WriteGuard, is_v2_relative_safe
from .paths import DATAPACKAGE
from .store import BLOB_DIR, hash_path

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
EXAMPLES = 50


def _plan_files(engine: Engine, plan_id: int) -> list[dict]:
    with engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                text(
                    """
                    SELECT k.dir, f.rel_path, f.sha256, f.size, b.state, b.method
                    FROM materialize_files f
                    JOIN materialize_packs k ON k.plan_id = f.plan_id AND k.pack_id = f.pack_id
                    JOIN materialize_blobs b ON b.plan_id = f.plan_id AND b.sha256 = f.sha256
                    WHERE f.plan_id = :p
                    ORDER BY k.dir, f.rel_path
                    """
                ),
                {"p": plan_id},
            ).mappings()
        ]


def _plan_blobs(engine: Engine, plan_id: int) -> dict[str, dict]:
    with engine.connect() as conn:
        return {
            r["sha256"]: dict(r)
            for r in conn.execute(
                text(
                    "SELECT sha256, size, state, method, source_kind FROM materialize_blobs "
                    "WHERE plan_id = :p"
                ),
                {"p": plan_id},
            ).mappings()
        }


def _plan_dirs(engine: Engine, plan_id: int) -> list[str]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                text("SELECT dir FROM materialize_packs WHERE plan_id = :p"), {"p": plan_id}
            ).scalars()
        )


def expected_paths(engine: Engine, plan_id: int) -> set[str]:
    """Every v2-relative path the plan owns (pack files, datapackage.json, store entries)."""
    out: set[str] = set()
    for f in _plan_files(engine, plan_id):
        out.add(f"{f['dir']}/{f['rel_path']}")
    for d in _plan_dirs(engine, plan_id):
        out.add(f"{d}/{DATAPACKAGE}")
    for sha in _plan_blobs(engine, plan_id):
        out.add(f"{BLOB_DIR}/{sha[:2]}/{sha[2:4]}/{sha}")
    return out


PLAN_DIR = ".forge-plan"  # plan exports (`plan --out`); never a stray, never gc'd


def walk_v2(v2_root: Path):
    """Yield v2-relative paths of every non-directory entry (symlinks are not followed)."""
    root = str(v2_root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            dirnames[:] = [d for d in dirnames if d != PLAN_DIR]
        for name in filenames + [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]:
            yield name if rel_dir == "." else f"{rel_dir}/{name}"


def verify(
    engine: Engine,
    plan_id: int,
    v2_root: Path,
    *,
    sample: int | None = 100,
    full: bool = False,
    seed: int | None = None,
    check_strays: bool = True,
) -> dict:
    files = _plan_files(engine, plan_id)
    blobs = _plan_blobs(engine, plan_id)
    store = v2_root / BLOB_DIR
    c: Counter = Counter()
    ex: dict[str, list] = defaultdict(list)

    def note(kind: str, item) -> None:
        c[kind] += 1
        if len(ex[kind]) < EXAMPLES:
            ex[kind].append(item)

    store_stat: dict[str, os.stat_result] = {}
    for sha, b in blobs.items():
        if b["state"] != "done":
            note(f"blob_{b['state']}", sha)
            continue
        p = store / sha[:2] / sha[2:4] / sha
        try:
            st = os.lstat(p)
        except FileNotFoundError:
            note("store_missing", sha)
            continue
        if not stat.S_ISREG(st.st_mode) or st.st_size != b["size"]:
            note("store_bad_size_or_type", sha)
            continue
        store_stat[sha] = st
        c["store_ok"] += 1

    links_seen: Counter = Counter()
    checkable: list[tuple[str, str, int, int]] = []  # (path, sha, ino, dev)
    for f in files:
        rel = f"{f['dir']}/{f['rel_path']}"
        if f["state"] != "done":
            note("file_blob_not_done", rel)
            continue
        p = v2_root / rel
        try:
            st = os.lstat(p)
        except FileNotFoundError:
            note("file_missing", rel)
            continue
        if not stat.S_ISREG(st.st_mode):
            note("file_not_regular", rel)
            continue
        if st.st_size != f["size"]:
            note("file_size_mismatch", rel)
            continue
        bst = store_stat.get(f["sha256"])
        if bst is not None and (st.st_ino, st.st_dev) == (bst.st_ino, bst.st_dev):
            c["file_hardlinked"] += 1
            links_seen[f["sha256"]] += 1
        else:
            c["file_copy"] += 1
        c["file_ok_stat"] += 1
        checkable.append((str(p), f["sha256"], st.st_ino, st.st_dev))

    # Link counts: the store inode must carry at least itself + every pack link we saw (+1 for
    # the source name when the blob came from a loose file).
    for sha, n in links_seen.items():
        st = store_stat[sha]
        expected = 1 + n + (1 if blobs[sha].get("method") == "linked" else 0)
        if st.st_nlink < expected:
            note("nlink_too_low", {"sha256": sha, "nlink": st.st_nlink, "expected": expected})
        else:
            c["nlink_ok"] += 1

    # sha256: one hash per inode.
    by_inode: dict[tuple[int, int], tuple[str, str]] = {}
    for path, sha, ino, dev in checkable:
        by_inode.setdefault((ino, dev), (path, sha))
    for sha, st in store_stat.items():
        by_inode.setdefault((st.st_ino, st.st_dev), (str(store / sha[:2] / sha[2:4] / sha), sha))
    inodes = sorted(by_inode.values())
    if not full and sample is not None and len(inodes) > sample:
        inodes = random.Random(seed).sample(inodes, sample)
    hashed_bytes = 0
    for path, sha in inodes:
        got, n = hash_path(path)
        hashed_bytes += n
        if got != sha:
            note("sha_mismatch", {"path": os.path.relpath(path, v2_root), "want": sha, "got": got})
        else:
            c["sha_ok"] += 1

    strays: list[str] = []
    if check_strays and v2_root.is_dir():
        expected = {f"{f['dir']}/{f['rel_path']}" for f in files}
        expected |= {f"{d}/{DATAPACKAGE}" for d in _plan_dirs(engine, plan_id)}
        expected |= {f"{BLOB_DIR}/{s[:2]}/{s[2:4]}/{s}" for s in blobs}
        for rel in walk_v2(v2_root):
            if rel not in expected:
                c["stray"] += 1
                if len(strays) < EXAMPLES:
                    strays.append(rel)

    bad = sum(
        c[k]
        for k in (
            "store_missing",
            "store_bad_size_or_type",
            "file_missing",
            "file_not_regular",
            "file_size_mismatch",
            "sha_mismatch",
            "nlink_too_low",
        )
    )
    return {
        "plan_id": plan_id,
        "mode": "all" if full else f"sample:{sample}",
        "files_planned": len(files),
        "blobs_planned": len(blobs),
        "inodes_hashed": len(inodes),
        "bytes_hashed": hashed_bytes,
        "counts": dict(sorted(c.items())),
        "examples": {k: v for k, v in ex.items()},
        "stray_examples": strays,
        "mismatches": c["sha_mismatch"],
        "problems": bad,
        "ok": bad == 0,
    }


def tree_hash(v2_root: Path) -> str:
    """Deterministic digest of the v2 tree: (path, sha256, nlink) for every file, with the
    ``materialized_at`` timestamp removed from datapackage.json. Used to prove a killed + resumed
    run equals an uninterrupted one."""
    h = hashlib.sha256()
    for rel in sorted(walk_v2(v2_root)):
        p = v2_root / rel
        st = os.lstat(p)
        if stat.S_ISLNK(st.st_mode):
            digest = "symlink:" + os.readlink(p)
        elif os.path.basename(rel) == DATAPACKAGE:
            fd = WriteGuard.open_read(p)
            try:
                raw = b""
                while chunk := os.read(fd, 1 << 20):
                    raw += chunk
            finally:
                os.close(fd)
            doc = json.loads(raw)
            doc.get("forge", {}).pop("materialized_at", None)
            digest = hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()
        else:
            digest, _ = hash_path(p)
        h.update(f"{rel}\0{digest}\0{st.st_nlink}\n".encode())
    return h.hexdigest()


# ------------------------------------------------------------------------------- audit-source


def audit_source(engine: Engine, source_root: Path, *, sample: int | None = None) -> dict:
    """Stat every present catalog source file (read-only). Reports missing / size / mtime drift."""
    c: Counter = Counter()
    ex: dict[str, list] = defaultdict(list)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT path, size, mtime FROM source_files WHERE present ORDER BY path")
        ).all()
    if sample is not None and len(rows) > sample:
        rows = random.Random(0).sample(rows, sample)
    for path, size, mtime in rows:
        if not is_v2_relative_safe(path):
            c["unsafe_path"] += 1
            continue
        try:
            st = os.stat(source_root / path, follow_symlinks=False)
        except FileNotFoundError:
            c["missing"] += 1
            if len(ex["missing"]) < EXAMPLES:
                ex["missing"].append(path)
            continue
        changed = False
        if st.st_size != size:
            c["size_changed"] += 1
            changed = True
            if len(ex["size_changed"]) < EXAMPLES:
                ex["size_changed"].append({"path": path, "catalog": size, "now": st.st_size})
        if st.st_mtime_ns // 1000 != (mtime - EPOCH) // timedelta(microseconds=1):
            c["mtime_changed"] += 1
            changed = True
            if len(ex["mtime_changed"]) < EXAMPLES:
                ex["mtime_changed"].append(path)
        c["changed" if changed else "unchanged"] += 1
    c["checked"] = len(rows)
    bad = c["missing"] + c["size_changed"] + c["mtime_changed"]
    return {
        "source_root": str(source_root),
        "counts": dict(sorted(c.items())),
        "examples": dict(ex),
        "ok": bad == 0,
    }


# --------------------------------------------------------------------------------- preflight


def _read_sysctl(name: str) -> str | None:
    try:
        with open(f"/proc/sys/{name.replace('.', '/')}") as f:
            return f.read().strip()
    except OSError:
        return None


def preflight(
    engine: Engine, guard: WriteGuard, source_root: Path, report: dict, *, sample: int = 20
) -> dict:
    """Cheap go/no-go before a long apply: can this pod hardlink real catalog files into v2?

    Links up to ``sample`` random present loose source files to
    ``<v2>/.forge-blobs/.preflight-*`` one at a time and removes each probe NAME again (the
    source files are not modified). EPERM usually means ``fs.protected_hardlinks=1`` and the pod
    UID neither owns the file nor may write it: apply would then fall back to full copies for
    such files. The owner/mode histogram tells you which ``runAsUser`` links the most.
    """
    out: dict = {"startup": report, "uid": os.getuid(), "gid": os.getgid()}
    out["protected_hardlinks"] = _read_sysctl("fs.protected_hardlinks")
    st = os.statvfs(guard.v2_root)
    out["v2_free_bytes"] = int(st.f_bavail * st.f_frsize)
    with engine.connect() as conn:
        rels = list(
            conn.execute(
                text(
                    "SELECT path FROM source_files WHERE present AND kind = 'loose' "
                    "ORDER BY random() LIMIT :n"
                ),
                {"n": max(1, sample)},
            ).scalars()
        )
    rels = [r for r in rels if is_v2_relative_safe(r)]
    if not rels:
        out["link_probe"] = {"ok": False, "error": "no loose source file in the catalog"}
        out["ok"] = False
        return out
    probe_dir = Path(guard.v2_root) / BLOB_DIR
    guard.mkdirs(probe_dir)
    linked = 0
    errors: Counter = Counter()
    owners: Counter = Counter()
    unchanged = True
    for rel in rels:
        src = source_root / rel
        try:
            sst = os.stat(src, follow_symlinks=False)
        except FileNotFoundError:
            errors["source_missing"] += 1
            continue
        owners[f"uid={sst.st_uid} mode={stat.S_IMODE(sst.st_mode):o}"] += 1
        probe = guard.new_temp_name(probe_dir, ".preflight-")
        try:
            guard.link(src, probe)
        except OSError as x:
            errors[errno.errorcode.get(x.errno, str(x.errno))] += 1
        else:
            if os.stat(probe).st_ino == sst.st_ino:
                linked += 1
            else:
                errors["different_inode"] += 1
            guard.unlink(probe)
        after = os.stat(src, follow_symlinks=False)
        unchanged &= (after.st_size, after.st_mtime_ns) == (sst.st_size, sst.st_mtime_ns)
    out["link_probe"] = {
        "ok": linked == len(rels),
        "sampled": len(rels),
        "linked": linked,
        "errors": dict(errors),
        "owners": dict(owners.most_common(10)),
    }
    out["source_unchanged"] = unchanged
    out["ok"] = bool(linked == len(rels) and unchanged)
    return out


# ----------------------------------------------------------------------------------- gc-plan


def gc_plan(
    engine: Engine,
    plan_id: int,
    guard: WriteGuard,
    *,
    apply_gc: bool = False,
) -> dict:
    """v2 entries not owned by the plan. With ``apply_gc`` they are unlinked (v2 only, via the
    guard), then empty directories are removed. The source tree is never walked."""
    v2 = Path(guard.v2_root)
    expected = expected_paths(engine, plan_id)
    strays = sorted(rel for rel in walk_v2(v2) if rel not in expected)
    removed = 0
    removed_dirs = 0
    if apply_gc:
        for rel in strays:
            try:
                guard.unlink(v2 / rel)
                removed += 1
            except FileNotFoundError:
                pass
        keep = {str(v2), str(v2 / BLOB_DIR), str(v2 / PLAN_DIR)}
        for dirpath, _dirnames, _files in sorted(
            os.walk(str(v2), topdown=False, followlinks=False), key=lambda t: -len(t[0])
        ):
            if (
                dirpath in keep
                or os.path.islink(dirpath)
                or dirpath.startswith(str(v2 / PLAN_DIR) + "/")
            ):
                continue
            try:
                if not os.listdir(dirpath):
                    guard.rmdir(dirpath)
                    removed_dirs += 1
            except (FileNotFoundError, OSError):
                pass
    return {
        "plan_id": plan_id,
        "strays": len(strays),
        "stray_paths": strays,
        "applied": apply_gc,
        "removed_files": removed,
        "removed_dirs": removed_dirs,
    }


# ------------------------------------------------------------------------------------ status


def status(engine: Engine, plan_id: int) -> dict:
    """Progress of one plan: units, blobs and packs by state, bytes done."""
    with engine.connect() as conn:

        def grouped(sql: str) -> dict:
            return {
                " ".join(str(x) for x in r[:-1]): int(r[-1])
                for r in conn.execute(text(sql), {"p": plan_id}).all()
            }

        plan = (
            conn.execute(
                text("SELECT id, status, created_at, totals FROM materialize_plans WHERE id = :p"),
                {"p": plan_id},
            )
            .mappings()
            .first()
        )
        return {
            "plan_id": plan_id,
            "plan_status": plan["status"] if plan else None,
            "created_at": plan["created_at"] if plan else None,
            "units": grouped(
                "SELECT kind, status, count(*) FROM materialize_units WHERE plan_id = :p "
                "GROUP BY 1, 2 ORDER BY 1, 2"
            ),
            "blobs": grouped(
                "SELECT state, coalesce(method, '-'), count(*) FROM materialize_blobs "
                "WHERE plan_id = :p GROUP BY 1, 2 ORDER BY 1, 2"
            ),
            "blob_bytes": grouped(
                "SELECT state, sum(size) FROM materialize_blobs WHERE plan_id = :p "
                "GROUP BY 1 ORDER BY 1"
            ),
            "packs": grouped(
                "SELECT status, count(*) FROM materialize_packs WHERE plan_id = :p "
                "GROUP BY 1 ORDER BY 1"
            ),
            "errors": [
                dict(r)
                for r in conn.execute(
                    text(
                        "SELECT 'unit' AS what, id::text AS id, error FROM materialize_units "
                        "WHERE plan_id = :p AND error IS NOT NULL "
                        "UNION ALL SELECT 'blob', sha256, error FROM materialize_blobs "
                        "WHERE plan_id = :p AND state = 'failed' "
                        "UNION ALL SELECT 'pack', pack_id::text, error FROM materialize_packs "
                        "WHERE plan_id = :p AND error IS NOT NULL LIMIT 50"
                    ),
                    {"p": plan_id},
                ).mappings()
            ],
            "totals": json.loads(plan["totals"]) if plan and plan["totals"] else None,
        }
