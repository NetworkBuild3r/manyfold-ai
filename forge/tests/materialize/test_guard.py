"""Write guard: every write target must resolve strictly under v2 (or scratch), never into the
source tree; startup refuses unsafe mount layouts (AC4). No database needed. INIT-032/SPEC-012."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from forge.materialize import guard as guard_mod
from forge.materialize.guard import GuardError, StartupError, join_v2, open_guard


@pytest.fixture
def roots(tmp_path):
    nas = tmp_path / "nas"
    src = nas / "3D-Prints"
    v2 = nas / "3D-Prints-v2"
    scratch = tmp_path / "scratch"
    for d in (src, v2, scratch):
        d.mkdir(parents=True)
    (src / "Anime").mkdir()
    (src / "Anime" / "model.stl").write_bytes(b"solid x\nendsolid x\n")
    g, report = open_guard(v2, src, scratch, shared_mount_ack=True)
    return SimpleNamespace(nas=nas, src=src, v2=v2, scratch=scratch, guard=g, report=report)


def test_accepts_paths_strictly_under_v2(roots) -> None:
    g = roots.guard
    assert g.check(roots.v2 / "Anime" / "Pack" / "a.stl") == str(roots.v2 / "Anime/Pack/a.stl")
    assert g.check(roots.scratch / "spool-1", "scratch") == str(roots.scratch / "spool-1")


@pytest.mark.parametrize(
    "target",
    [
        "/etc/passwd",
        "/tmp/forge-escape",
        "relative/path.stl",
        "{v2}",  # the root itself is not writable
        "{v2}/..",
        "{v2}/.",
        "{v2}/a/../../3D-Prints/x.stl",
        "{v2}/../3D-Prints/x.stl",
        "{src}",
        "{src}/Anime/model.stl",
        "{src}/new.stl",
        "{v2}/a\x00b",
        "{scratch}/x",  # scratch is not the v2 area
    ],
)
def test_rejects_outside_or_source(roots, target) -> None:
    path = target.format(v2=roots.v2, src=roots.src, scratch=roots.scratch)
    with pytest.raises(GuardError):
        roots.guard.check(path, "v2")


def test_rejects_bytes_path(roots) -> None:
    with pytest.raises(GuardError):
        roots.guard.check(os.fsencode(str(roots.v2 / "x")), "v2")


def test_symlink_inside_v2_pointing_at_source_is_refused(roots) -> None:
    (roots.v2 / "evil").symlink_to(roots.src)
    with pytest.raises(GuardError, match="SOURCE"):
        roots.guard.check(roots.v2 / "evil" / "Anime" / "model.stl")
    with pytest.raises(GuardError, match="SOURCE"):
        roots.guard.mkdirs(roots.v2 / "evil" / "Anime" / "new")
    with pytest.raises(GuardError):
        roots.guard.open_new(roots.v2 / "evil" / "pwned.stl")
    assert not (roots.src / "pwned.stl").exists()


def test_symlink_inside_v2_pointing_outside_is_refused(roots, tmp_path) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (roots.v2 / "out").symlink_to(outside)
    with pytest.raises(GuardError, match="outside"):
        roots.guard.open_new(roots.v2 / "out" / "x")
    assert not (outside / "x").exists()


def test_scratch_writes_cannot_reach_source(roots) -> None:
    (roots.scratch / "lnk").symlink_to(roots.src)
    with pytest.raises(GuardError):
        roots.guard.open_new(roots.scratch / "lnk" / "x", "scratch")


def test_primitives_refuse_source_targets(roots) -> None:
    g = roots.guard
    model = roots.src / "Anime" / "model.stl"
    before = model.read_bytes(), model.stat().st_mtime_ns
    with pytest.raises(GuardError):
        g.unlink(model)
    with pytest.raises(GuardError):
        g.rename(model, roots.v2 / "stolen.stl")
    with pytest.raises(GuardError):
        g.rename(roots.v2 / "x", model)
    with pytest.raises(GuardError):
        g.link(roots.v2 / "x", roots.src / "Anime" / "linked.stl")
    with pytest.raises(GuardError):
        g.open_new(roots.src / "Anime" / "new.stl")
    with pytest.raises(GuardError):
        g.mkdirs(roots.src / "Anime" / "newdir")
    with pytest.raises(GuardError):
        g.rmdir(roots.src / "Anime")
    with pytest.raises(GuardError):
        g.rmtree_scratch(roots.src)
    assert (model.read_bytes(), model.stat().st_mtime_ns) == before
    assert sorted(p.name for p in (roots.src / "Anime").iterdir()) == ["model.stl"]


def test_link_from_source_adds_a_name_only(roots) -> None:
    model = roots.src / "Anime" / "model.stl"
    st0 = model.stat()
    dst = roots.v2 / "blob"
    roots.guard.link(model, dst)
    st1 = model.stat()
    assert dst.stat().st_ino == st0.st_ino
    assert (st1.st_size, st1.st_mtime_ns, model.read_bytes()) == (
        st0.st_size,
        st0.st_mtime_ns,
        b"solid x\nendsolid x\n",
    )
    assert st1.st_nlink == st0.st_nlink + 1


def test_open_new_never_opens_an_existing_inode(roots) -> None:
    """A v2 name may be a hardlink of a source inode: it must never be opened for write."""
    model = roots.src / "Anime" / "model.stl"
    roots.guard.link(model, roots.v2 / "alias.stl")
    with pytest.raises(FileExistsError):
        roots.guard.open_new(roots.v2 / "alias.stl")
    assert model.read_bytes() == b"solid x\nendsolid x\n"


def test_link_refuses_symlink_source(roots) -> None:
    (roots.v2 / "s").symlink_to(roots.src / "Anime" / "model.stl")
    with pytest.raises(GuardError, match="regular"):
        roots.guard.link(roots.v2 / "s", roots.v2 / "t")


def test_read_only_flag_assertion() -> None:
    guard_mod.WriteGuard.assert_read_only_flags(os.O_RDONLY | os.O_NOFOLLOW)
    for flags in (os.O_WRONLY, os.O_RDWR, os.O_CREAT, os.O_TRUNC, os.O_APPEND):
        with pytest.raises(GuardError):
            guard_mod.WriteGuard.assert_read_only_flags(flags)


@pytest.mark.parametrize("rel", ["../x", "a/../../b", "/abs", "a//b", "./a", "a/.", "", "a\x00"])
def test_join_v2_rejects_unsafe_plan_paths(roots, rel) -> None:
    with pytest.raises(GuardError):
        join_v2(roots.guard, rel)


# ------------------------------------------------------------------------- startup (AC4)


def _fake_mounts(monkeypatch, *, same_dev: bool, readonly: bool) -> None:
    real_stat, real_statvfs = os.stat, os.statvfs

    def fake_stat(path, *a, **kw):
        st = real_stat(path, *a, **kw)
        if not same_dev and "3D-Prints-v2" not in os.fspath(path):
            return SimpleNamespace(st_dev=st.st_dev + 1)
        return st

    def fake_statvfs(path):
        st = real_statvfs(path)
        flag = (st.f_flag | os.ST_RDONLY) if readonly else (st.f_flag & ~os.ST_RDONLY)
        return SimpleNamespace(f_flag=flag)

    monkeypatch.setattr(guard_mod, "_stat", fake_stat)
    monkeypatch.setattr(guard_mod, "_statvfs", fake_statvfs)


def test_startup_fails_when_separate_source_mount_is_writable(roots, monkeypatch) -> None:
    _fake_mounts(monkeypatch, same_dev=False, readonly=False)
    with pytest.raises(StartupError, match="WRITABLE"):
        open_guard(roots.v2, roots.src, roots.scratch, shared_mount_ack=True)


def test_startup_ok_when_separate_source_mount_is_read_only(roots, monkeypatch) -> None:
    _fake_mounts(monkeypatch, same_dev=False, readonly=True)
    _, report = open_guard(roots.v2, roots.src, roots.scratch)
    assert report.source_readonly_mount and not report.same_device


def test_startup_shared_writable_mount_needs_explicit_ack(roots, monkeypatch) -> None:
    _fake_mounts(monkeypatch, same_dev=True, readonly=False)
    with pytest.raises(StartupError, match="FORGE_SOURCE_SHARED_MOUNT"):
        open_guard(roots.v2, roots.src, roots.scratch, shared_mount_ack=False)
    _, report = open_guard(roots.v2, roots.src, roots.scratch, shared_mount_ack=True)
    assert report.same_device and report.shared_mount_acknowledged


@pytest.mark.parametrize(
    "layout",
    [
        ("{src}/v2", "{src}", "{scratch}"),  # v2 inside source
        ("{nas}", "{src}", "{scratch}"),  # source inside v2
        ("{src}", "{src}", "{scratch}"),  # same dir
        ("{v2}", "{src}", "{src}/tmp"),  # scratch inside source
        ("{v2}", "{src}", "{v2}/tmp"),  # scratch inside v2
    ],
)
def test_startup_rejects_overlapping_roots(roots, layout) -> None:
    fmt = {"src": roots.src, "v2": roots.v2, "nas": roots.nas, "scratch": roots.scratch}
    v2, src, scratch = (p.format(**fmt) for p in layout)
    os.makedirs(v2, exist_ok=True)
    os.makedirs(scratch, exist_ok=True)
    with pytest.raises(StartupError, match="overlap"):
        open_guard(v2, src, scratch, shared_mount_ack=True)


def test_startup_rejects_relative_and_missing_roots(roots) -> None:
    with pytest.raises(StartupError, match="absolute"):
        open_guard("v2", roots.src, roots.scratch, shared_mount_ack=True)
    with pytest.raises(StartupError, match="not a directory"):
        open_guard(roots.nas / "nope", roots.src, roots.scratch, shared_mount_ack=True)


def test_startup_rejects_network_scratch(roots, monkeypatch) -> None:
    monkeypatch.setattr(guard_mod, "mount_fstype", lambda p: "nfs4")
    with pytest.raises(StartupError, match="network"):
        open_guard(roots.v2, roots.src, roots.scratch, shared_mount_ack=True)
