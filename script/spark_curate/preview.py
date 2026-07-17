from __future__ import annotations

import io
import zipfile
from pathlib import Path

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
ARCHIVE_EXT = {".zip", ".rar", ".7z", ".cbz"}
# Prefer these basenames for Manyfold
PREFERRED_NAMES = (
    "preview.jpg",
    "preview.jpeg",
    "preview.png",
    "preview.webp",
    "cover.jpg",
    "cover.png",
    "thumb.jpg",
    "thumb.png",
    "thumbnail.jpg",
)


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXT


def list_images(folder: Path, max_depth: int = 2) -> list[Path]:
    found: list[Path] = []
    if not folder.is_dir():
        return found
    for p in folder.rglob("*"):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(folder)
        except ValueError:
            continue
        if len(rel.parts) - 1 > max_depth:
            continue
        # skip deep cache dirs
        if any(part.startswith(".") for part in rel.parts[:-1]):
            continue
        if is_image(p):
            found.append(p)
    return found


def score_image(path: Path) -> tuple[int, int, int]:
    """Higher is better: preferred name, then size, then shorter path."""
    name = path.name.lower()
    preferred = 0
    for i, pref in enumerate(PREFERRED_NAMES):
        if name == pref:
            preferred = 100 - i
            break
    if preferred == 0 and name.startswith("preview"):
        preferred = 50
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    # Prefer larger product shots over tiny icons; cap so path still matters
    size_score = min(size, 5_000_000)
    depth_penalty = len(path.parts)
    return (preferred, size_score, -depth_penalty)


def best_image(folder: Path) -> Path | None:
    images = list_images(folder)
    if not images:
        return None
    images.sort(key=score_image, reverse=True)
    # Skip tiny icons (< 3 KB)
    for img in images:
        try:
            if img.stat().st_size >= 3000:
                return img
        except OSError:
            continue
    return images[0]


def try_extract_preview_from_zip(folder: Path, cache_dir: Path) -> Path | None:
    """
    If no on-disk image, pull the largest image entry from the first zip into cache.
    Never modifies the zip; writes only under cache_dir. Does not extract rar/7z
    (needs external tools).
    """
    zips = sorted(folder.glob("*.zip")) + sorted(folder.glob("*.ZIP"))
    if not zips:
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    for zpath in zips[:3]:
        try:
            with zipfile.ZipFile(zpath, "r") as zf:
                candidates: list[tuple[int, str]] = []
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    name = info.filename
                    lower = name.lower()
                    if not any(lower.endswith(ext) for ext in IMAGE_EXT):
                        continue
                    if info.file_size < 3000:
                        continue
                    # skip __MACOSX
                    if "__macosx" in lower.replace("\\", "/"):
                        continue
                    candidates.append((info.file_size, name))
                if not candidates:
                    continue
                candidates.sort(reverse=True)
                _, member = candidates[0]
                data = zf.read(member)
                ext = Path(member).suffix.lower() or ".jpg"
                out = cache_dir / f"{folder.name[:40].strip()}.preview{ext}"
                out.write_bytes(data)
                return out
        except (zipfile.BadZipFile, OSError, KeyError, RuntimeError):
            continue
    return None


def load_image_as_jpeg_bytes(path: Path, max_edge: int = 1024, quality: int = 85) -> bytes:
    """
    Return JPEG bytes, optionally resized. Uses Pillow if available; otherwise
    returns original file bytes (may be png).
    """
    raw = path.read_bytes()
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        # Pass through; many vision APIs accept png/jpeg
        return raw

    img = Image.open(io.BytesIO(raw))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    elif img.mode == "L":
        img = img.convert("RGB")
    w, h = img.size
    scale = min(1.0, float(max_edge) / max(w, h, 1))
    if scale < 1.0:
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()
