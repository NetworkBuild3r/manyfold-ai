# Manyfold file organization toolkit

## Goal

Turn a messy dump into a **Manyfold library**:

```text
\\192.168.11.102\Backups\3D-Prints\
  Anime\
    Model Name\
      part.stl
      preview.jpg
  Cosplay\
  D&D\
  DC\
  Games\
  Movie TV\
  ...
```

| Folder | Role |
|--------|------|
| `3D-Prints` | **Organized** — point Manyfold’s library path here (or a Docker mount of it) |
| `3D-Prints-Unorg` | **Inbox** — dumps, packs, opaque `GAMEBODY#`, loose Etsy zips |

**Rule of thumb:** one **model** = one **folder** under a **category**. Manyfold scans that.

---

## Tooling (in this repo)

| Script | Purpose |
|--------|---------|
| `inventory-catalog.ps1` | Scan Unorg, pull previews, build visual gallery |
| `extract-zip-previews.ps1` | Pull images **out of** `.zip` dumps into `images/` + `preview.*` so Manyfold can show them |
| `cleanup-unorg-duplicates.ps1` | Remove `Copy of …` / `(1)` dumps and same-size duplicates; optional full folder drop |
| `organize-from-decisions.ps1` | Apply gallery “Move” decisions into `3D-Prints` |
| `organize-unorg.ps1` | Bulk auto-map buckets (dry-run / apply) without reviewing thumbs |

---

## Workflow (recommended)

### 1. Build the visual inventory

```powershell
cd C:\Users\BrianNelson\Projects\manyfold-ai

# Start with a few buckets (faster)
.\script\inventory-catalog.ps1 -Buckets 'Dragon Ball Z','Star Wars','Halo','Sailor Moon'

# Or full Unorg (slow on NAS — run overnight if huge)
.\script\inventory-catalog.ps1
```

Output (default):

```text
\\192.168.11.102\Backups\3D-Prints-Unorg\.inventory\
  index.html      ← open this in a browser
  catalog.json
  thumbs\         ← extracted preview images
```

```powershell
start "\\192.168.11.102\Backups\3D-Prints-Unorg\.inventory\index.html"
```

### 2. Review in the gallery

- **See every design** with a thumbnail when an image exists  
- **Search / filter** by bucket, category, has-image / no-image  
- Set **category** (Anime, Cosplay, D&D, …)  
- Mark **Move** or **Skip**  
- Decisions stay in **browser localStorage** until you export  

**Accept all suggested** = mark every Unorg item Move with the auto-suggested category (good first pass).

### 3. Export and apply

In the gallery: **Export decisions.json** (downloads to your Downloads folder).

```powershell
# Dry-run
.\script\organize-from-decisions.ps1 -DecisionsPath "$env:USERPROFILE\Downloads\decisions.json"

# Really move
.\script\organize-from-decisions.ps1 -DecisionsPath "$env:USERPROFILE\Downloads\decisions.json" -Apply
```

### 4. Tell Manyfold

1. Library path in Manyfold should be the **organized** root (or Docker mount of it).  
2. In UI: **Scan for new files**.  
3. Manyfold creates models from category subfolders.

---

## How images are found

For each model folder the catalog picks the best image in order:

1. `preview.jpg` / `preview.png` / `cover.*` / `thumb.*`  
2. Largest image in the folder root  
3. First large image under `images/`  
4. One level of subfolders  

For **loose archives** (Etsy `.rar`/`.zip`): companion image with the same basename if present; otherwise “No preview” (you still see name + path).

**Tip for inventory quality:** when dumping packs, keep the product photo next to the zip/folder.

### Clean duplicates / drop a junk bucket

```powershell
cd C:\Users\BrianNelson\Projects\manyfold-ai

# Dry-run: "Copy of …", "name (1).zip", same-name+size in one folder
.\script\cleanup-unorg-duplicates.ps1

# Apply name-pattern cleanup on whole Unorg
.\script\cleanup-unorg-duplicates.ps1 -NamePatternsOnly -Apply

# Delete an entire bad dump folder (e.g. etsy full of Copy of …)
.\script\cleanup-unorg-duplicates.ps1 -DropPath 'W:\3D-Prints-Unorg\etsy' -Apply

# Optional content-hash pass (slow)
.\script\cleanup-unorg-duplicates.ps1 -ContentHash -Apply
```

Logs: `3D-Prints-Unorg\.manyfold-organize-logs\cleanup-duplicates-*.json`

### Extract previews from zips (Manyfold + gallery)

Product shots are often *inside* the zip. Manyfold only sees files on disk, so run:

```powershell
cd C:\Users\BrianNelson\Projects\manyfold-ai

# Dry-run a bucket first
.\script\extract-zip-previews.ps1 -Buckets 'etsy','Dragon Ball Z'

# Write files
.\script\extract-zip-previews.ps1 -Buckets 'etsy','Dragon Ball Z' -Apply

# Full Unorg (slow on NAS)
.\script\extract-zip-previews.ps1 -Apply

# Also organized library
.\script\extract-zip-previews.ps1 -AlsoOrganized -Apply
```

| Output | Purpose |
|--------|---------|
| `<model>\images\*.jpg/png/...` | Images from the zip (up to 30, skips tiny icons) |
| `<model>\preview.jpg` (or `.png`) | Best product shot for Manyfold / inventory |

Then rescan the library in Manyfold (or re-run `inventory-catalog.ps1`).

---

## Fast paths (no gallery)

Auto-map known buckets (names only, no thumbs):

```powershell
# Plan
.\script\organize-unorg.ps1 -Buckets 'Dragon Ball Z','Star Wars','DC' 

# Apply
.\script\organize-unorg.ps1 -Buckets 'Dragon Ball Z','Star Wars','DC' -Apply -SkipImagesOnly
```

Use the **gallery** for messy dumps (`Gamebody`, `Marvel Files`, `Mixed`, `etsy`).

---

## Manyfold Docker mount

If the app runs in Docker, the host library should map to the **organized** tree, e.g. in `.env`:

```env
LIBRARY_MOUNT=//192.168.11.102/Backups/3D-Prints
```

Then in Manyfold add/edit library path: `/libraries/prints` (or your compose mount target).

---

## Limits

- Inventory gallery itself does **not** unpack archives; run `extract-zip-previews.ps1 -Apply` first so images land on disk.  
- `.rar` / `.7z` are not handled yet (use 7-Zip manually or convert to zip).  
- NAS scans are I/O heavy; use `-Buckets` for batches.  
- Gallery is static HTML + local thumbs; no server required.
