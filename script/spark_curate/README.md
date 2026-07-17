# Spark Curate — Manyfold library organizer

Automated **rearrange-only** organizer for a Manyfold library (`Category/ModelName/`) using your **DGX Spark**:

| Service | Role |
|---------|------|
| Gemma 4 vision `:11435` | See preview → name, category, tags, confidence |
| Qwen 1.5B `:11436` | Normalize JSON / enum categories |
| NudeNet `:8090` | Sensitive flag (CPU) |
| Optional embed `:8000` | Reserved for later near-dup |

**Never deletes** files or folders. Only `shutil.move` to a new `Category/Model` path (with unique suffix if needed).  
Default mode is **dry-run**.

---

## Manyfold layout

```text
3D-Prints/
  Anime/
    Model Name/
      *.stl|*.3mf|archives
      preview.jpg          ← ideal
  Cosplay/
  ...
  .spark-curate/           ← logs, decisions, thumb cache (created)
```

---

## Quick start

From a machine that can reach the NAS share **and** Spark (`192.168.11.161`):

```powershell
cd C:\Users\BrianNelson\Projects\manyfold-ai

# Optional: example config
python script/spark_curate --write-example-config script/spark_curate.config.json

# Ping Spark
python script/spark_curate --smoke

# Pilot: one category, 20 folders, dry-run
python script/spark_curate `
  --library "\\192.168.11.102\Backups\3D-Prints" `
  --category Cosplay `
  --limit 20

# Full library dry-run (slow)
python script/spark_curate --library "\\192.168.11.102\Backups\3D-Prints"

# Apply rearrangements (confidence >= 0.55 by default)
python script/spark_curate --library "\\192.168.11.102\Backups\3D-Prints" --apply
```

Optional Pillow for image resize (recommended):

```powershell
pip install pillow
```

---

## Outputs (under `<library>/.spark-curate/`)

| File | Purpose |
|------|---------|
| `decisions-*.jsonl` | Full LLM decisions per model folder |
| `audit-*.jsonl` | What would move / did move |
| `run-*.log` | Human-readable log |
| `summary-*.json` | Counts |
| `thumbs/` | Images extracted from zips when no on-disk preview |

Each applied move may also write `Model/.spark-curate-meta.json` (tags, sensitive, previous path) — Manyfold ignores unknown files.

---

## Policy (no human in the loop)

| Confidence | Behavior |
|------------|----------|
| `>= min_confidence` (default **0.55**) | `rename` / `move` executed when `--apply` |
| below threshold | Left in place (`SKIP low conf`) |
| no preview image | Left in place (never deleted) |
| `is_junk` | **Still kept** — only noted, never deleted |

Raise bar:

```powershell
python script/spark_curate --min-confidence 0.75 --apply
```

---

## Flags

| Flag | Meaning |
|------|---------|
| `--apply` | Perform moves |
| `--limit N` | First N model folders only |
| `--category NAME` | Only that top-level category (repeatable) |
| `--workers N` | Parallel Gemma jobs (default 2; keep low) |
| `--skip-good` | Skip folders with `preview.jpg` not under `Unknown` |
| `--config path.json` | Endpoints + library overrides |
| `--smoke` | Health-check Spark APIs |

---

## After a successful apply

1. Manyfold UI → **Scan for new files** / detect filesystem changes  
2. Optional: filter **With images only** once that build is deployed  
3. Review `.spark-curate/audit-*.jsonl` if anything looks wrong — sources were **moved**, not deleted; reverse from audit paths if needed

---

## VRAM / ops

- Stop **ComfyUI / Wan I2V** while batching Gemma (`systemctl --user stop comfyui`)  
- NudeNet is CPU-only and safe alongside vLLM  
- Prefer LAN `192.168.11.161` over Tailscale for bulk vision  

---

## Config snippet

```json
{
  "spark": {
    "gemma_url": "http://192.168.11.161:11435/v1",
    "gemma_model": "gemma4-uncensored",
    "curator_url": "http://192.168.11.161:11436/v1",
    "curator_model": "qwen2.5-1.5b-instruct",
    "nudenet_url": "http://192.168.11.161:8090"
  },
  "curate": {
    "library_root": "\\\\192.168.11.102\\Backups\\3D-Prints",
    "min_confidence": 0.55,
    "workers": 2,
    "categories": ["Anime", "Cosplay", "Cartoons", "D&D", "DC", "Games", "Movie TV", "Unknown", "WICKED", "Cults3D", "AnySTL", "B3dserk"]
  }
}
```
