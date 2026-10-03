"""Materializer fixtures: a fake NAS (``nas/3D-Prints`` source + ``nas/3D-Prints-v2``) in
``tmp_path`` (one filesystem, so hardlinks are real), cataloged by the REAL walker + sweep engine,
then packs inserted the way SPEC-010/011 will. INIT-032/SPEC-012."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "engine"
MAT_TABLES = (
    "materialize_files",
    "materialize_packs",
    "materialize_blobs",
    "materialize_units",
    "materialize_plans",
)
FAST_ENV = {
    "FORGE_SWEEP_POLL_SECONDS": "0.1",
    "FORGE_SWEEP_REAP_SECONDS": "0.2",
    "FORGE_SWEEP_HEARTBEAT_SECONDS": "0.5",
    "FORGE_SWEEP_HEARTBEAT_STALE_SECONDS": "3",
    "FORGE_MATERIALIZE_POLL_SECONDS": "0.1",
    "FORGE_MATERIALIZE_HEARTBEAT_SECONDS": "0.5",
}


def _native() -> bool:
    try:
        import forge.engine._libarchive  # noqa: F401
    except (OSError, TypeError, AttributeError, ImportError):
        return False
    return True


NATIVE = _native()
if os.environ.get("FORGE_REQUIRE_NATIVE") == "1" and not NATIVE:
    raise RuntimeError("libarchive.so.13 is required (FORGE_REQUIRE_NATIVE=1)")
needs_native = pytest.mark.skipif(not NATIVE, reason="libarchive.so.13 not available")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stl(seed: str, triangles: int = 4) -> bytes:
    """A small binary STL whose bytes are unique per seed."""
    header = seed.encode().ljust(80, b"\0")[:80]
    body = b""
    for i in range(triangles):
        digest = hashlib.sha256(f"{seed}:{i}".encode()).digest()
        vals = [float(digest[j] % 100) / 10 for j in range(12)]
        body += struct.pack("<12fH", *vals, 0)
    return header + struct.pack("<I", triangles) + body


def zip_bytes(members: dict[str, bytes], *, stored: bool = False) -> bytes:
    buf = io.BytesIO()
    method = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(buf, "w", method) as z:
        for name, data in members.items():
            info = zipfile.ZipInfo(name, date_time=(2024, 1, 1, 0, 0, 0))
            info.compress_type = method
            z.writestr(info, data)
    return buf.getvalue()


SHARED = {f"shared{i}.stl": stl(f"shared{i}", 6) for i in (1, 2, 3)}
HERO_BODY = stl("hero-body", 8)
KNIGHT = stl("knight", 5)
BASE = stl("bonus-base", 3)
JPEG = b"\xff\xd8\xff\xe0" + b"hero-preview" * 20 + b"\xff\xd9"
README = b"Hero pack readme\n"


def knight_zip(knight: bytes) -> bytes:
    """Stored (uncompressed) so a same-length tamper keeps the archive size identical."""
    return zip_bytes(
        {**{f"stl/{k}": v for k, v in SHARED.items()}, "stl/knight.stl": knight}, stored=True
    )


@dataclass
class MatEnv:
    tmp: Path
    nas: Path
    src: Path
    v2: Path
    scratch: Path
    db_url: str
    engine: Engine

    # ---------------------------------------------------------------------------- source tree
    def write(self, rel: str, data: bytes) -> Path:
        p = self.src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def copy_fixture(self, name: str, rel: str) -> Path:
        p = self.src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURES / name, p)
        return p

    def build_library(self) -> None:
        """Pack A (Anime/Hero): loose files + Hero.zip (3 shared STLs, readme, nested zip with
        a base STL, macOS junk). Pack B (Games/Knight): Knight.zip with the same 3 shared STLs.
        Pack C (Terrain/Ruins): a 3-part RAR5 volume set + a zip inside a rar."""
        self.write("Anime/Hero/hero_body.stl", HERO_BODY)
        self.write("Anime/Hero/preview.jpg", JPEG)
        self.write("Anime/Hero/shared1.stl", SHARED["shared1.stl"])
        extras = zip_bytes({"bonus/base.stl": BASE, "bonus/._base.stl": b"\0\5\26\7junk"})
        self.write(
            "Anime/Hero/Hero.zip",
            zip_bytes(
                {
                    **{f"parts/{k}": v for k, v in SHARED.items()},
                    "docs/readme.txt": README,
                    "__MACOSX/parts/._shared2.stl": b"\0\5\26\7junk",
                    "extras.zip": extras,
                }
            ),
        )
        self.write("Games/Knight/Knight.zip", knight_zip(KNIGHT))
        for i in (1, 2, 3):
            self.copy_fixture(f"split_rar5.part{i}.rar", f"Terrain/Ruins/Ruins.part{i}.rar")
        self.copy_fixture("zip_in_rar.rar", "Terrain/Ruins/extras.rar")

    def catalog(self) -> None:
        """Real walk + real sweep (engine) -> blobs, occurrences, containers."""
        from forge.sweep import SweepSettings, worker_loop
        from forge.walker import run

        run(source_root=self.src, db_url=self.db_url, threads=2)
        stats = worker_loop("test-sweep", SweepSettings.from_env(), db_url=self.db_url, once=True)
        assert stats.processed, "sweep processed nothing"
        bad = self.rows(
            "SELECT id, kind::text, status::text, failure_reason::text FROM containers "
            "WHERE status <> 'done'"
        )
        assert not bad, f"catalog has unfinished containers: {bad}"

    # -------------------------------------------------------------------------------- packs
    def container_of(self, rel: str) -> int:
        return int(
            self.scalar(
                """
                SELECT cf.container_id FROM container_files cf
                JOIN source_files sf ON sf.id = cf.source_file_id
                JOIN containers c ON c.id = cf.container_id
                WHERE sf.path = :p AND c.parent_container_id IS NULL
                ORDER BY c.id DESC LIMIT 1
                """,
                p=rel,
            )
        )

    def pack(
        self,
        name: str | None,
        category: str | None,
        containers: list[tuple[int, str]],
        *,
        status: str = "resolved",
        creator: str | None = None,
        source_tag: str | None = None,
    ) -> int:
        with self.engine.begin() as conn:
            pid = int(
                conn.execute(
                    text(
                        """
                        INSERT INTO packs (name, category, creator, source_tag, status)
                        VALUES (:n, :c, :cr, :st, CAST(:s AS pack_status)) RETURNING id
                        """
                    ),
                    {"n": name, "c": category, "cr": creator, "st": source_tag, "s": status},
                ).scalar_one()
            )
            for cid, role in containers:
                conn.execute(
                    text(
                        "INSERT INTO pack_containers (pack_id, container_id, role) "
                        "VALUES (:p, :c, CAST(:r AS pack_container_role))"
                    ),
                    {"p": pid, "c": cid, "r": role},
                )
        return pid

    def standard_packs(self) -> dict[str, int]:
        hero_zip = self.container_of("Anime/Hero/Hero.zip")
        loose = self.container_of("Anime/Hero/hero_body.stl")
        knight = self.container_of("Games/Knight/Knight.zip")
        ruins = self.container_of("Terrain/Ruins/Ruins.part1.rar")
        extras = self.container_of("Terrain/Ruins/extras.rar")
        return {
            "hero": self.pack(
                "Hero",
                "Anime",
                [(hero_zip, "primary"), (loose, "source")],
                creator="Sculptor X",
                source_tag="Cults3D",
            ),
            "knight": self.pack("Knight", "Games", [(knight, "primary")]),
            "ruins": self.pack("Ruins", "Terrain", [(ruins, "primary"), (extras, "source")]),
        }

    # ------------------------------------------------------------------------------- running
    def settings(self, **kw):
        from forge.materialize.apply import ApplySettings

        return ApplySettings.from_env(**kw)

    def plan(self, **kw):
        from forge.materialize.plan import PlanOptions, build_plan

        return build_plan(self.engine, PlanOptions(**kw))

    def apply(self, **kw) -> int:
        from forge.materialize.apply import main_apply

        settings_kw = {k: kw.pop(k) for k in list(kw) if k in ("procs", "allow_copy")}
        return main_apply(self.settings(**settings_kw), self.db_url, **kw)

    def verify(self, **kw) -> dict:
        from forge.materialize.apply import active_plan_id
        from forge.materialize.verify import verify

        kw.setdefault("full", True)
        return verify(self.engine, active_plan_id(self.engine), self.v2, **kw)

    def scalar(self, sql: str, **params):
        with self.engine.connect() as conn:
            return conn.execute(text(sql), params).scalar()

    def rows(self, sql: str, **params):
        with self.engine.connect() as conn:
            return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]

    def execute(self, sql: str, **params) -> None:
        with self.engine.begin() as conn:
            conn.execute(text(sql), params)

    def source_snapshot(self) -> dict[str, tuple]:
        """(sha256, size, mtime_ns, mode) of every source file — must never change."""
        out = {}
        for p in sorted(self.src.rglob("*")):
            if p.is_file() and not p.is_symlink():
                st = p.stat()
                out[str(p.relative_to(self.src))] = (
                    sha(p.read_bytes()),
                    st.st_size,
                    st.st_mtime_ns,
                    st.st_mode,
                )
        return out


@pytest.fixture
def mat(tmp_path, monkeypatch, session, engine, migrated_db) -> MatEnv:
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(MAT_TABLES)} RESTART IDENTITY CASCADE"))
    nas = tmp_path / "nas"
    src, v2, scratch = nas / "3D-Prints", nas / "3D-Prints-v2", tmp_path / "scratch"
    for d in (src, v2, scratch):
        d.mkdir(parents=True)
    monkeypatch.setenv("FORGE_SOURCE_ROOT", str(src))
    monkeypatch.setenv("FORGE_V2_ROOT", str(v2))
    monkeypatch.setenv("FORGE_SCRATCH", str(scratch))
    monkeypatch.setenv("FORGE_SOURCE_SHARED_MOUNT", "1")
    monkeypatch.delenv("FORGE_MATERIALIZE_TEST_KILL_AFTER", raising=False)
    for k, v in FAST_ENV.items():
        monkeypatch.setenv(k, v)
    return MatEnv(tmp_path, nas, src, v2, scratch, migrated_db, engine)


@pytest.fixture
def library(mat) -> tuple[MatEnv, dict[str, int]]:
    mat.build_library()
    mat.catalog()
    return mat, mat.standard_packs()
