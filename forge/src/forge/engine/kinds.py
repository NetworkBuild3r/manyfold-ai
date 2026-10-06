"""Member kind classification (blob.kind ∈ mesh, image, archive, doc, other) and archive magic."""

from __future__ import annotations

MAGIC_BYTES = 512  # enough for tar's "ustar" at offset 257

MESH_EXT = frozenset(
    {
        "stl", "obj", "3mf", "ply", "fbx", "glb", "gltf", "amf", "off", "3ds", "dae", "x3d",
        "wrl", "vrml", "blend", "step", "stp", "iges", "igs", "f3d", "skp", "fcstd", "scad",
        "ztl", "zpr", "ma", "mb", "max", "c4d", "lwo", "usd", "usda", "usdc", "usdz", "abc",
        # slicer / resin print files
        "lys", "lyt", "chitubox", "ctb", "cbddlp", "photon", "photons", "pwmx", "pwms", "pwma",
        "pws", "pw0", "pwmo", "pwmb", "pwx", "dlp", "goo", "prz", "jxs", "zcode", "sl1",
        "sl1s", "gcode", "bgcode", "ufp", "fdg",
    }
)  # fmt: skip
IMAGE_EXT = frozenset(
    {
        "png", "jpg", "jpeg", "gif", "bmp", "webp", "tif", "tiff", "svg", "heic", "heif",
        "avif", "psd", "tga", "ico", "jfif", "dds", "exr", "hdr",
    }
)  # fmt: skip
DOC_EXT = frozenset(
    {"pdf", "txt", "md", "rtf", "doc", "docx", "odt", "ods", "odp", "xlsx", "pptx", "epub",
     "html", "htm", "nfo", "url", "csv"}
)  # fmt: skip
# ZIP-based application files: hashed as one blob, never opened as archives.
OPAQUE_EXT = frozenset(
    {
        "jar",
        "apk",
        "aab",
        "whl",
        "nupkg",
        "xpi",
        "crx",
        "vsix",
        "ipa",
        "exe",
        "msi",
        "dll",
    }
)


def magic_format(head: bytes) -> str | None:
    """Archive/compression format from leading bytes, or ``None``."""
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "zip"
    if head.startswith(b"Rar!\x1a\x07\x01\x00"):
        return "rar5"
    if head.startswith(b"Rar!\x1a\x07\x00"):
        return "rar4"
    if head.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "7z"
    if head.startswith(b"\x1f\x8b"):
        return "gzip"
    if (
        len(head) >= 10
        and head[:3] == b"BZh"
        and 0x31 <= head[3] <= 0x39
        and head[4:10] in (b"\x31\x41\x59\x26\x53\x59", b"\x17\x72\x45\x38\x50\x90")
    ):
        return "bzip2"
    if head.startswith(b"\xfd7zXZ\x00"):
        return "xz"
    if head.startswith(b"\x28\xb5\x2f\xfd"):
        return "zstd"
    if head.startswith(b"\x04\x22\x4d\x18"):
        return "lz4"
    if head.startswith(b"MSCF\x00\x00\x00\x00"):
        return "cab"
    if len(head) >= 262 and head[257:262] == b"ustar":
        return "tar"
    return None


def extension(name: str) -> str:
    base = name.rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


# Archive formats whose signature is absent or beyond MAGIC_BYTES: the extension alone decides.
_EXTENSION_ONLY_ARCHIVE = frozenset({"tar", "iso", "lzh", "lha", "arj"})


def classify(name: str, head: bytes) -> str:
    """Kind of a member. A known mesh/image/doc extension wins over magic (3MF, FCStd and
    friends are ZIP containers but are meshes). Otherwise ``archive`` when the bytes carry an
    archive signature, whatever the name; an archive *extension* without one (the library's
    ``model_file.bin.gz`` exports are plain binary, a raw ``.002`` split volume is mid-stream)
    is ``other`` and is never opened as a container."""
    ext = extension(name)
    if ext in MESH_EXT:
        return "mesh"
    if ext in IMAGE_EXT:
        return "image"
    if ext in DOC_EXT:
        return "doc"
    if ext in OPAQUE_EXT:
        return "other"
    if magic_format(head) is not None or ext in _EXTENSION_ONLY_ARCHIVE:
        return "archive"
    return "other"
