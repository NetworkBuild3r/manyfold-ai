"""Static fence: only ``forge/materialize/guard.py`` may call filesystem write primitives.

Every other materialize module must go through :class:`WriteGuard` (whose primitives check that
the target resolves under v2/scratch and never under the source root). Fails the build if a
write primitive, a write-mode ``open()``, ``shutil``/``tempfile`` or a raw ``os.open`` appears
anywhere else in the package. INIT-032/SPEC-012.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2] / "src" / "forge" / "materialize"
GUARD = "guard.py"

# Attribute calls that write/modify the filesystem, whatever the receiver (os., Path, shutil...).
FORBIDDEN_ATTRS = {
    "link",
    "symlink",
    "rename",
    "replace",
    "unlink",
    "remove",
    "rmdir",
    "removedirs",
    "mkdir",
    "makedirs",
    "chmod",
    "lchmod",
    "chown",
    "lchown",
    "utime",
    "truncate",
    "ftruncate",
    "mkfifo",
    "mknod",
    "write_text",
    "write_bytes",
    "touch",
    "symlink_to",
    "hardlink_to",
    "rmtree",
    "copy",
    "copy2",
    "copyfile",
    "copytree",
    "move",
    "mkstemp",
    "mkdtemp",
    "NamedTemporaryFile",
    "TemporaryDirectory",
}
# Calls of these on the guard object are the sanctioned path.
GUARD_RECEIVERS = {"guard", "self.guard", "g"}
FORBIDDEN_MODULES = {"shutil", "tempfile"}


def _receiver(node: ast.Attribute) -> str:
    parts = []
    cur = node.value
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), str(path))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
            for n in names:
                if n and n.split(".")[0] in FORBIDDEN_MODULES:
                    out.append(f"{path.name}:{node.lineno} imports {n}")
            if isinstance(node, ast.ImportFrom) and node.module == "os":
                for a in node.names:
                    if a.name in FORBIDDEN_ATTRS or a.name == "open":
                        out.append(f"{path.name}:{node.lineno} from os import {a.name}")
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Attribute):
            recv = _receiver(f)
            # str.replace(old, new) / dict.copy() are not filesystem calls; os.replace(a, b),
            # Path.replace(target) and shutil.copy(a, b) are.
            if f.attr == "replace" and recv != "os" and len(node.args) != 1:
                continue
            if f.attr == "copy" and recv != "shutil" and len(node.args) < 2:
                continue
            if f.attr in FORBIDDEN_ATTRS and recv not in GUARD_RECEIVERS:
                out.append(f"{path.name}:{node.lineno} calls {recv}.{f.attr}()")
            if f.attr == "open" and recv == "os":
                out.append(f"{path.name}:{node.lineno} calls os.open() (use WriteGuard.open_read)")
        if isinstance(f, ast.Name) and f.id == "open":
            mode = None
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                mode = node.args[1].value
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = kw.value.value
            if mode is None and (len(node.args) >= 2 or node.keywords):
                out.append(f"{path.name}:{node.lineno} open() with a non-literal mode")
            elif mode is not None and set(mode) & set("wax+"):
                out.append(f"{path.name}:{node.lineno} open(..., {mode!r})")
    return out


MODULES = sorted(p for p in PKG.glob("*.py") if p.name != GUARD)


def test_package_has_modules() -> None:
    names = {p.name for p in MODULES}
    assert {"apply.py", "extract.py", "plan.py", "store.py", "verify.py"} <= names


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_write_primitives_outside_guard(path: Path) -> None:
    assert _violations(path) == []


def test_fence_catches_a_planted_violation(tmp_path) -> None:
    """A fence that has never failed is not a fence."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "import os, shutil\n"
        "from pathlib import Path\n"
        "os.unlink('/x')\n"
        "Path('/x').write_bytes(b'')\n"
        "open('/x', 'wb')\n"
        "os.open('/x', 0)\n"
        "os.replace('/a', '/b')\n"
        "Path('/a').replace('/b')\n"
        "'abc'.replace('a', 'b')\n"
        "guard.unlink('/ok')\n"
    )
    v = _violations(planted)
    assert any("imports shutil" in x for x in v)
    assert any("os.unlink" in x for x in v)
    assert any("write_bytes" in x for x in v)
    assert any("open(..., 'wb')" in x for x in v)
    assert any("os.open" in x for x in v)
    assert any("os.replace" in x for x in v)
    assert any(":8 calls .replace()" in x for x in v)  # Path(...).replace(target)
    assert not any(":9 " in x for x in v)  # str.replace(old, new)
    assert not any("guard.unlink" in x for x in v)
