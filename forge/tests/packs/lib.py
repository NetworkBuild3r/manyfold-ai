"""Catalog builder + fake OpenAI-compatible LLM server for packs / classify tests.

INIT-032/SPEC-010 + SPEC-011
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sqlalchemy import text
from sqlalchemy.engine import Engine

from forge.db.models import join_member_path
from forge.packs.llm import LlmEndpoint

MY_TABLES = ("classify_decisions", "classify_overrides", "tag_decisions", "tag_overrides")


def sha(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _kind(name: str) -> str:
    ext = posixpath.splitext(name)[1].lower()
    if ext in (".stl", ".obj", ".3mf"):
        return "mesh"
    if ext in (".jpg", ".png"):
        return "image"
    if ext in (".zip", ".rar", ".7z"):
        return "archive"
    if ext in (".json", ".txt", ".pdf"):
        return "doc"
    return "other"


class Library:
    """Writes source_files / containers / blobs / occurrences directly (no NAS, no engine)."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def _blob(self, conn, name: str, seed: str, size: int | None, tri: int | None) -> str:
        digest = sha(seed)
        conn.execute(
            text(
                """
                INSERT INTO blobs (sha256, size, kind, ext, stl_triangles)
                VALUES (:s, :size, CAST(:k AS blob_kind), :ext, :tri)
                ON CONFLICT (sha256) DO NOTHING
                """
            ),
            {
                "s": digest,
                "size": size if size is not None else 1000 + len(seed),
                "k": _kind(name),
                "ext": posixpath.splitext(name)[1].lstrip(".").lower() or None,
                "tri": tri if tri is not None else (100 if _kind(name) == "mesh" else None),
            },
        )
        return digest

    def _source(self, conn, path: str, kind: str) -> int:
        return int(
            conn.execute(
                text(
                    """
                    INSERT INTO source_files (path, size, mtime, kind)
                    VALUES (:p, 10, :m, CAST(:k AS source_file_kind)) RETURNING id
                    """
                ),
                {"p": path, "m": datetime(2026, 1, 1, tzinfo=UTC), "k": kind},
            ).scalar_one()
        )

    def _occ(self, conn, cid: int, chain: list[str], digest: str, depth: int) -> None:
        conn.execute(
            text(
                """
                INSERT INTO occurrences (blob_sha, container_id, member_chain, member_path, depth)
                VALUES (:b, :c, CAST(:ch AS text[]), :mp, :d)
                """
            ),
            {"b": digest, "c": cid, "ch": chain, "mp": join_member_path(chain), "d": depth},
        )

    def archive(
        self,
        path: str,
        members: dict[str, str],
        *,
        status: str = "done",
        nested: dict[str, dict[str, str]] | None = None,
        sizes: dict[str, int] | None = None,
    ) -> int:
        """members: member name -> content seed. nested: inner archive name -> its members."""
        sizes = sizes or {}
        with self.engine.begin() as conn:
            sid = self._source(conn, path, "archive")
            cid = int(
                conn.execute(
                    text(
                        """
                        INSERT INTO containers (source_file_id, kind, format, depth, status)
                        VALUES (:s, 'archive', 'zip', 1, CAST(:st AS container_status))
                        RETURNING id
                        """
                    ),
                    {"s": sid, "st": status},
                ).scalar_one()
            )
            conn.execute(
                text(
                    "INSERT INTO container_files (container_id, source_file_id, ordinal) "
                    "VALUES (:c, :s, 1)"
                ),
                {"c": cid, "s": sid},
            )
            if status == "done":
                for name, seed in members.items():
                    d = self._blob(conn, name, seed, sizes.get(name), None)
                    self._occ(conn, cid, [name], d, 1)
            for inner, inner_members in (nested or {}).items():
                ad = self._blob(conn, inner, "archive:" + inner + path, None, None)
                self._occ(conn, cid, [inner], ad, 1)
                nid = int(
                    conn.execute(
                        text(
                            """
                            INSERT INTO containers (source_file_id, blob_sha, parent_container_id,
                                parent_chain, kind, depth, status)
                            VALUES (:s, :b, :p, CAST(:ch AS text[]), 'nested', 2,
                                CAST(:st AS container_status))
                            RETURNING id
                            """
                        ),
                        {"s": sid, "b": ad, "p": cid, "ch": [inner], "st": status},
                    ).scalar_one()
                )
                if status == "done":
                    for name, seed in inner_members.items():
                        d = self._blob(conn, name, seed, sizes.get(name), None)
                        self._occ(conn, nid, [inner, name], d, 2)
        return cid

    def loose(self, files: dict[str, str], *, status: str = "done") -> int:
        """files: relative path -> content seed. One loose_batch container for all of them."""
        with self.engine.begin() as conn:
            ids = [self._source(conn, p, "loose") for p in files]
            cid = int(
                conn.execute(
                    text(
                        """
                        INSERT INTO containers (source_file_id, kind, depth, status)
                        VALUES (:s, 'loose_batch', 0, CAST(:st AS container_status)) RETURNING id
                        """
                    ),
                    {"s": ids[0], "st": status},
                ).scalar_one()
            )
            for i, (sid, (path, seed)) in enumerate(zip(ids, files.items(), strict=True), 1):
                conn.execute(
                    text(
                        "INSERT INTO container_files (container_id, source_file_id, ordinal) "
                        "VALUES (:c, :s, :o)"
                    ),
                    {"c": cid, "s": sid, "o": i},
                )
                if status == "done":
                    d = self._blob(conn, path, seed, None, None)
                    self._occ(conn, cid, [path], d, 0)
        return cid

    def set_status(self, cid: int, status: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text("UPDATE containers SET status = CAST(:s AS container_status) WHERE id = :c"),
                {"s": status, "c": cid},
            )

    def scalar(self, sql: str, **params):
        with self.engine.connect() as conn:
            return conn.execute(text(sql), params).scalar()

    def rows(self, sql: str, **params) -> list:
        with self.engine.connect() as conn:
            return conn.execute(text(sql), params).all()

    def packs_of(self) -> list[set[str]]:
        """Final packs as sets of unit keys (sorted for stable asserts)."""
        rows = self.rows(
            "SELECT pack_id, unit_key FROM pack_units WHERE pack_id IS NOT NULL ORDER BY pack_id"
        )
        out: dict[int, set[str]] = {}
        for pid, key in rows:
            out.setdefault(pid, set()).add(key)
        return sorted(out.values(), key=lambda s: sorted(s))


# ------------------------------------------------------------------------------------- fake LLM


class FakeLlm:
    """OpenAI-compatible stub: ``POST /chat/completions`` via responder(body) -> content |
    (status, body), and ``GET /models`` listing ``models`` (``None`` -> HTTP 503). When ``serves``
    is a set, a chat request for any other model answers 404 like a real server."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.model_gets = 0
        self.models: list[str] | None = ["fake-qwen"]
        self.serves: set[str] | None = None
        self.responder: Callable[[dict], object] = lambda body: json.dumps(
            {"verdict": "separate", "confidence": 0.9, "reason": "default"}
        )
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # silence
                return

            def _send(self, status: int, data: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # noqa: N802
                if not self.path.rstrip("/").endswith("/models"):
                    self._send(404, b"{}")
                    return
                fake.model_gets += 1
                if fake.models is None:
                    self._send(503, b"{}")
                    return
                listing = [{"id": m, "object": "model"} for m in fake.models]
                self._send(200, json.dumps({"object": "list", "data": listing}).encode())

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                fake.requests.append({"path": self.path, "body": body})
                if fake.serves is not None and body.get("model") not in fake.serves:
                    err = {"error": {"message": f"The model `{body.get('model')}` does not exist."}}
                    self._send(404, json.dumps(err).encode())
                    return
                out = fake.responder(body)
                status = 200
                if isinstance(out, tuple):
                    status, payload = out
                    data = payload.encode()
                else:
                    data = json.dumps(
                        {"choices": [{"message": {"role": "assistant", "content": out}}]}
                    ).encode()
                self._send(status, data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    @property
    def endpoint(self) -> LlmEndpoint:
        # Built directly: the env path (LlmEndpoint.from_env) refuses loopback by design.
        return LlmEndpoint(url=self.url, model="fake-qwen")

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
