"""Sweep progress for humans (``forge status``) and Prometheus (``/metrics``). INIT-032/SPEC-007.

Throughput is NAS bytes: ``containers.source_bytes`` (sum of the source file sizes) of top-level
containers finished in the window. ETA = source bytes still pending/claimed / the 30-minute rate
(5-minute rate when the 30-minute window is empty).
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sqlalchemy import text
from sqlalchemy.engine import Engine

WINDOWS = {"5m": 300, "30m": 1800}


def collect_status(engine: Engine) -> dict:
    snap: dict = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds")}
    with engine.connect() as conn:
        snap["containers"] = [
            {
                "kind": kind,
                "status": status,
                "count": int(n),
                "members": int(members),
                "bytes_read": int(bytes_read),
                "source_bytes": int(source_bytes),
            }
            for kind, status, n, members, bytes_read, source_bytes in conn.execute(
                text(
                    """
                    SELECT kind::text, status::text, count(*), coalesce(sum(members), 0),
                           coalesce(sum(bytes_read), 0), coalesce(sum(source_bytes), 0)
                    FROM containers GROUP BY 1, 2 ORDER BY 1, 2
                    """
                )
            ).all()
        ]
        snap["failures"] = [
            {"kind": kind, "reason": reason, "count": int(n)}
            for kind, reason, n in conn.execute(
                text(
                    """
                    SELECT kind::text, coalesce(failure_reason::text, 'unknown'), count(*)
                    FROM containers WHERE status = 'failed' GROUP BY 1, 2 ORDER BY 3 DESC
                    """
                )
            ).all()
        ]
        snap["requeued_as_loose"] = int(
            conn.execute(
                text("SELECT count(*) FROM containers WHERE requeued_from_id IS NOT NULL")
            ).scalar_one()
        )
        snap["blobs"] = int(conn.execute(text("SELECT count(*) FROM blobs")).scalar_one())
        snap["occurrences"] = int(
            conn.execute(text("SELECT count(*) FROM occurrences")).scalar_one()
        )
        rem_count, rem_bytes = conn.execute(
            text(
                """
                SELECT count(DISTINCT c.id), coalesce(sum(sf.size), 0)
                FROM containers c
                JOIN container_files cf ON cf.container_id = c.id
                JOIN source_files sf ON sf.id = cf.source_file_id
                WHERE c.status IN ('pending', 'claimed') AND c.kind <> 'nested'
                """
            )
        ).one()
        snap["remaining_containers"] = int(rem_count)
        snap["source_bytes_remaining"] = int(rem_bytes)
        done_bytes, read_bytes, first, last = conn.execute(
            text(
                """
                SELECT coalesce(sum(source_bytes), 0), coalesce(sum(bytes_read), 0),
                       min(finished_at), max(finished_at)
                FROM containers
                WHERE kind <> 'nested' AND finished_at IS NOT NULL
                """
            )
        ).one()
        snap["source_bytes_done"] = int(done_bytes)
        snap["bytes_read"] = int(read_bytes)
        snap["first_finished_at"] = first.isoformat(timespec="seconds") if first else None
        snap["last_finished_at"] = last.isoformat(timespec="seconds") if last else None
        snap["rates"] = {}
        for name, secs in WINDOWS.items():
            n, sb, br = conn.execute(
                text(
                    """
                    SELECT count(*), coalesce(sum(source_bytes), 0), coalesce(sum(bytes_read), 0)
                    FROM containers
                    WHERE kind <> 'nested'
                      AND finished_at > now() - make_interval(secs => :secs)
                    """
                ),
                {"secs": secs},
            ).one()
            snap["rates"][name] = {
                "containers_per_min": round(int(n) * 60 / secs, 2),
                "source_bytes_per_s": round(int(sb) / secs, 1),
                "bytes_read_per_s": round(int(br) / secs, 1),
            }
        snap["workers"] = [
            {
                "worker_id": w,
                "host": host,
                "age_s": round(float(age), 1),
                "current_container_id": cur,
                "containers_done": int(d),
                "containers_failed": int(f),
                "source_bytes": int(sb),
            }
            for w, host, age, cur, d, f, sb in conn.execute(
                text(
                    """
                    SELECT worker_id, host, extract(epoch FROM now() - last_seen),
                           current_container_id, containers_done, containers_failed, source_bytes
                    FROM sweep_workers
                    WHERE last_seen > now() - interval '15 minutes'
                    ORDER BY worker_id
                    """
                )
            ).all()
        ]
    snap["workers_alive"] = sum(1 for w in snap["workers"] if w["age_s"] < 120)
    rate = snap["rates"]["30m"]["source_bytes_per_s"] or snap["rates"]["5m"]["source_bytes_per_s"]
    snap["eta_seconds"] = round(snap["source_bytes_remaining"] / rate) if rate > 0 else None
    return snap


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1000 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1000
    return f"{n:.1f} TB"


def _fmt_eta(seconds: int | None) -> str:
    if seconds is None:
        return "unknown (no containers finished in the last 30 min)"
    h, rem = divmod(int(seconds), 3600)
    return f"{h}h{rem // 60:02d}m"


def format_status(snap: dict) -> str:
    lines = [f"forge status @ {snap['generated_at']}", "", "containers (kind x status):"]
    lines.append(f"  {'kind':<12}{'status':<10}{'count':>10}{'members':>12}{'source':>12}")
    for row in snap["containers"]:
        lines.append(
            f"  {row['kind']:<12}{row['status']:<10}{row['count']:>10}{row['members']:>12}"
            f"{_fmt_bytes(row['source_bytes']):>12}"
        )
    lines.append("")
    lines.append("failures by reason:")
    if not snap["failures"]:
        lines.append("  (none)")
    for row in snap["failures"]:
        lines.append(f"  {row['kind']:<12}{row['reason']:<22}{row['count']:>8}")
    lines.append(f"  re-queued not-an-archive -> loose_batch: {snap['requeued_as_loose']}")
    lines.append("")
    lines.append(f"blobs: {snap['blobs']}   occurrences: {snap['occurrences']}")
    lines.append(
        f"source bytes done: {_fmt_bytes(snap['source_bytes_done'])}   "
        f"remaining: {_fmt_bytes(snap['source_bytes_remaining'])} "
        f"in {snap['remaining_containers']} containers"
    )
    lines.append(f"uncompressed bytes hashed: {_fmt_bytes(snap['bytes_read'])}")
    for name, r in snap["rates"].items():
        lines.append(
            f"rate {name:>3}: {_fmt_bytes(r['source_bytes_per_s'])}/s source, "
            f"{_fmt_bytes(r['bytes_read_per_s'])}/s hashed, "
            f"{r['containers_per_min']} containers/min"
        )
    lines.append(f"ETA: {_fmt_eta(snap['eta_seconds'])}")
    lines.append(f"workers alive: {snap['workers_alive']}")
    for w in snap["workers"]:
        lines.append(
            f"  {w['worker_id']:<40} seen {w['age_s']:>6}s ago  current={w['current_container_id']}"
            f"  done={w['containers_done']} failed={w['containers_failed']}"
        )
    return "\n".join(lines)


def _esc(v: str) -> str:
    return v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def metrics_text(snap: dict) -> str:
    out: list[str] = []

    def gauge(name: str, help_text: str, samples: list[tuple[dict, float]]) -> None:
        out.append(f"# HELP {name} {help_text}")
        out.append(f"# TYPE {name} gauge")
        for labels, value in samples:
            lab = ",".join(f'{k}="{_esc(str(v))}"' for k, v in labels.items())
            out.append(f"{name}{{{lab}}} {value}" if lab else f"{name} {value}")

    gauge("forge_up", "1 when the status snapshot succeeded", [({}, 1)])
    gauge(
        "forge_containers",
        "Containers by kind and status",
        [({"kind": r["kind"], "status": r["status"]}, r["count"]) for r in snap["containers"]],
    )
    gauge(
        "forge_container_failures",
        "Failed containers by kind and failure reason",
        [({"kind": r["kind"], "reason": r["reason"]}, r["count"]) for r in snap["failures"]],
    )
    gauge(
        "forge_requeued_as_loose",
        "Not-an-archive containers re-queued as loose_batch",
        [({}, snap["requeued_as_loose"])],
    )
    gauge("forge_blobs", "Distinct blobs (SHA-256)", [({}, snap["blobs"])])
    gauge("forge_occurrences", "Occurrence rows", [({}, snap["occurrences"])])
    gauge(
        "forge_source_bytes_done",
        "NAS bytes of finished top-level containers",
        [({}, snap["source_bytes_done"])],
    )
    gauge(
        "forge_source_bytes_remaining",
        "NAS bytes of pending/claimed containers",
        [({}, snap["source_bytes_remaining"])],
    )
    gauge(
        "forge_bytes_read",
        "Uncompressed bytes hashed (top-level containers)",
        [({}, snap["bytes_read"])],
    )
    gauge(
        "forge_source_bytes_per_second",
        "NAS bytes/s of containers finished in the window",
        [({"window": k}, r["source_bytes_per_s"]) for k, r in snap["rates"].items()],
    )
    gauge(
        "forge_containers_per_minute",
        "Top-level containers finished per minute in the window",
        [({"window": k}, r["containers_per_min"]) for k, r in snap["rates"].items()],
    )
    gauge(
        "forge_eta_seconds",
        "Remaining NAS bytes / 30m rate (-1 = unknown)",
        [({}, snap["eta_seconds"] if snap["eta_seconds"] is not None else -1)],
    )
    gauge(
        "forge_workers_alive",
        "Worker processes with a heartbeat in the last 2 min",
        [({}, snap["workers_alive"])],
    )
    return "\n".join(out) + "\n"


class _Cache:
    def __init__(self, engine: Engine, ttl: float) -> None:
        self.engine = engine
        self.ttl = ttl
        self.lock = threading.Lock()
        self.at = 0.0
        self.body: str | None = None

    def get(self) -> str:
        with self.lock:
            if self.body is None or time.monotonic() - self.at > self.ttl:
                try:
                    self.body = metrics_text(collect_status(self.engine))
                except Exception as exc:  # noqa: BLE001 - scrape must answer, not crash
                    self.body = (
                        "# HELP forge_up 1 when the status snapshot succeeded\n"
                        f"# TYPE forge_up gauge\nforge_up 0\n# error {type(exc).__name__}\n"
                    )
                self.at = time.monotonic()
            return self.body


def serve_metrics(engine: Engine, port: int, ttl: float = 30.0) -> ThreadingHTTPServer:
    """Start a daemon-thread HTTP server: GET /metrics (text format), GET /healthz."""
    cache = _Cache(engine, ttl)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/metrics"):
                body = cache.get().encode()
                ctype = "text/plain; version=0.0.4; charset=utf-8"
            elif self.path.startswith("/healthz"):
                body, ctype = b"ok\n", "text/plain"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args) -> None:
            pass

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="metrics", daemon=True).start()
    return server


def main_status(*, as_json: bool) -> int:
    from forge.config import ConfigError
    from forge.db.session import get_engine

    try:
        engine = get_engine()
        snap = collect_status(engine)
    except ConfigError as exc:
        import sys

        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(snap, indent=2) if as_json else format_status(snap))
    return 0
