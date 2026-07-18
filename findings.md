# Findings: Blank card previews

## Critical

1. Cards emit `<img>` for `preview_file` even when the file/folder is gone on NFS → browser broken-image glyph with alt from filename (`Preview`, `Black`).
2. Live: ~1802 of ~6965 previews missing on disk; ~4035 models with `Problem :missing` (whole folder absent).
3. Examples: `DC/0002 - Samurai Batman…/preview.jpg` and `Cosplay/01 alien/BLACK.png` — folders renamed/deleted; sibling folders still exist.
4. `send_file_content` rescues `Errno::ENOENT` with **500** and does not rescue `Shrine::FileNotFound` → card thumbs 500.

## Medium

5. `has_image` filter only checks image extension on `preview_file_id`, not on-disk existence.
6. `ParseMetadataJob#resolve_preview_file` can keep a missing image preview forever.
