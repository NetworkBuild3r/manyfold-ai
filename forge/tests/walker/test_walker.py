"""SPEC-005 walker ACs (AC2 hashing dropped — see SPEC-007)."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import select
from tests.helpers import add_blob
from tests.walker.conftest import RAR5_MAGIC, ZIP_MAGIC

from forge.cli import main
from forge.db.enums import ContainerKind, ContainerStatus, FailureReason, SourceFileKind
from forge.db.models import Container, ContainerFile, Occurrence, SourceFile
from forge.walker import group_archive_sets, run, walk_tree


def _files(session) -> dict[str, SourceFile]:
    return {row.path: row for row in session.scalars(select(SourceFile)).all()}


def _containers(session) -> list[Container]:
    return list(session.scalars(select(Container)).all())


def _members(session, container: Container) -> list[str]:
    rows = session.execute(
        select(SourceFile.path, ContainerFile.ordinal)
        .join(ContainerFile, ContainerFile.source_file_id == SourceFile.id)
        .where(ContainerFile.container_id == container.id)
        .order_by(ContainerFile.ordinal)
    ).all()
    return [path for path, _ord in rows]


def test_dry_run_fixture_counts(fixture_tree: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("FORGE_SOURCE_ROOT", str(fixture_tree))
    monkeypatch.delenv("FORGE_DB_URL", raising=False)
    assert main(["walk", "--dry-run", "--threads", "2"]) == 0
    out = capsys.readouterr().out
    parsed = dict(line.split("\t", 1) for line in out.strip().splitlines())
    assert parsed["files"] == "8"
    assert parsed["archives"] == "6"
    assert parsed["loose"] == "2"
    assert parsed["symlinks"] == "1"
    assert parsed["skipped_dirs"] == "1"
    assert int(parsed["containers_seeded"]) >= 4  # zip + set + gap + >=1 loose batch
    assert parsed["new"] == "0"


def test_inventory_kinds_and_split_set(walked_db, session) -> None:
    files = _files(session)
    assert "link-to-stl" not in files
    assert ".manyfold/preview.png" not in files
    assert files["loose/model.stl"].kind is SourceFileKind.loose
    assert files["loose/photo.jpg"].kind is SourceFileKind.loose
    assert files["archive/pack.zip"].kind is SourceFileKind.archive
    assert files["archive/pack.zip"].format == "zip"
    for part in (1, 2, 3):
        rec = files[f"split/set.part{part}.rar"]
        assert rec.kind is SourceFileKind.archive
        assert rec.format == "rar5"
        assert rec.volume_set == "split/set|part"

    containers = _containers(session)
    archives = [c for c in containers if c.kind is ContainerKind.archive]
    loose_batches = [c for c in containers if c.kind is ContainerKind.loose_batch]
    assert len(loose_batches) == 1
    assert {p for c in loose_batches for p in _members(session, c)} == {
        "loose/model.stl",
        "loose/photo.jpg",
    }

    split = next(c for c in archives if "set.part1.rar" in " ".join(_members(session, c)))
    assert split.status is ContainerStatus.pending
    assert split.failure_reason is None
    assert _members(session, split) == [
        "split/set.part1.rar",
        "split/set.part2.rar",
        "split/set.part3.rar",
    ]

    zip_c = next(c for c in archives if _members(session, c) == ["archive/pack.zip"])
    assert zip_c.status is ContainerStatus.pending
    assert zip_c.format == "zip"
    assert zip_c.depth == 1
    assert loose_batches[0].depth == 0


def test_missing_volume_set(walked_db, session) -> None:
    gap = next(
        c
        for c in _containers(session)
        if c.kind is ContainerKind.archive and c.failure_reason is FailureReason.missing_volume
    )
    assert gap.status is ContainerStatus.failed
    assert _members(session, gap) == ["gap/broken.part1.rar", "gap/broken.part3.rar"]


def test_second_walk_reprocesses_nothing(walked_db, session, fixture_tree: Path) -> None:
    second = run(source_root=fixture_tree, dry_run=False, threads=2)
    session.expire_all()
    assert second.counts.new == 0
    assert second.counts.changed == 0
    assert second.counts.vanished == 0
    assert second.counts.unchanged == 8
    assert second.counts.containers_seeded == 0


def test_touch_resets_exactly_one_container(walked_db, session, fixture_tree: Path) -> None:
    zip_c = next(c for c in _containers(session) if _members(session, c) == ["archive/pack.zip"])
    split = next(
        c for c in _containers(session) if "set.part1.rar" in " ".join(_members(session, c))
    )
    blob = add_blob(session, b"occ")
    session.add(
        Occurrence.from_chain(
            blob_sha=blob.sha256,
            container_id=zip_c.id,
            member_chain=("archive/pack.zip",),
            depth=0,
        )
    )
    zip_c.status = ContainerStatus.done
    zip_c.attempts = 3
    split.status = ContainerStatus.done
    split.attempts = 2
    session.commit()

    zip_path = fixture_tree / "archive" / "pack.zip"
    now = zip_path.stat().st_mtime + 10
    os.utime(zip_path, (now, now))
    zip_path.write_bytes(ZIP_MAGIC + b"zip-body-changed")

    result = run(source_root=fixture_tree, dry_run=False, threads=2)
    session.expire_all()
    assert result.counts.changed == 1
    assert result.counts.containers_seeded == 1

    zip_c = session.get(Container, zip_c.id)
    split = session.get(Container, split.id)
    assert zip_c is not None and split is not None
    assert zip_c.status is ContainerStatus.pending
    assert zip_c.attempts == 0
    assert split.status is ContainerStatus.done
    assert split.attempts == 2
    leftover = session.scalars(select(Occurrence).where(Occurrence.container_id == zip_c.id)).all()
    assert leftover == []


def test_vanished_marked_not_deleted(walked_db, session, fixture_tree: Path) -> None:
    target = fixture_tree / "loose" / "photo.jpg"
    target.unlink()
    run(source_root=fixture_tree, dry_run=False, threads=2)
    session.expire_all()
    rec = session.scalars(select(SourceFile).where(SourceFile.path == "loose/photo.jpg")).one()
    assert rec.present is False


def test_readonly_fixture_dir(fixture_tree: Path, monkeypatch) -> None:
    for dirpath, dirnames, filenames in os.walk(fixture_tree):
        os.chmod(dirpath, 0o555)
        for name in filenames:
            os.chmod(os.path.join(dirpath, name), 0o444)
    try:
        result = run(source_root=fixture_tree, dry_run=True, threads=2)
        assert result.counts.files == 8
        assert result.dry_run is True
    finally:
        for dirpath, dirnames, filenames in os.walk(fixture_tree):
            os.chmod(dirpath, 0o755)
            for name in filenames:
                path = os.path.join(dirpath, name)
                if not os.path.islink(path):
                    os.chmod(path, 0o644)


def test_never_opens_source_for_write(fixture_tree: Path, monkeypatch) -> None:
    real_open = os.open
    root = os.path.abspath(fixture_tree)

    def guarded(path, flags, mode=0o777, **kwargs):
        abs_path = os.path.abspath(path) if isinstance(path, str | os.PathLike) else path
        write_bits = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
        if isinstance(abs_path, str) and abs_path.startswith(root + os.sep):
            if flags & write_bits:
                raise AssertionError(f"write open under source: {abs_path} flags={flags}")
        return real_open(path, flags, mode, **kwargs)

    monkeypatch.setattr(os, "open", guarded)
    monkeypatch.setenv("FORGE_SOURCE_ROOT", str(fixture_tree))
    result = run(source_root=fixture_tree, dry_run=True, threads=2)
    assert result.counts.files == 8


def test_lone_partn_is_single_volume(tmp_path: Path) -> None:
    folder = tmp_path / "Model.part2"
    folder.mkdir()
    (folder / "Model.part2.rar").write_bytes(RAR5_MAGIC + b"solo")
    files, _counts = walk_tree(tmp_path, threads=1)
    _annotated, groups = group_archive_sets(files)
    assert len(groups) == 1
    assert groups[0].missing_volume is False
    assert len(groups[0].files) == 1
    assert groups[0].volume_set is None
