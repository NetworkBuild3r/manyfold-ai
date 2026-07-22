# Findings: Archive contents scanner

- Archives already indexable as ModelFile; upload fully extracts via Archive::Reader.
- Library scan never opened archives before this work.
- Runtime Docker image has ImageMagick + libarchive, not Node.
- Previews stored under `{model}/.manyfold/derivatives/archives/{file_public_id}/{entry_public_id}/preview.png`
- Mesh cache under `{model}/.manyfold/archive_cache/...` for WebGL content URL.
