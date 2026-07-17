# spark-curate

**Standalone Docker service** that reorganizes a 3D-print library into Manyfold-friendly layout:

```text
/library/<Category>/<Model Name>/
```

It is **not** part of the Manyfold web UI, Rails app, or `manyfold` k8s deployment.  
It only needs:

1. A **volume** with your `3D-Prints` tree  
2. Network access to **DGX Spark** (Gemma vision, Qwen curator, NudeNet)

**Never deletes** data — only rearranges via `move`. Default is **dry-run**.

---

## Architecture

```text
┌──────────────────────────┐     HTTP      ┌─────────────────────┐
│  spark-curate container  │ ────────────► │ DGX Spark           │
│  (this project)          │               │ :11435 Gemma vision │
│  mount: /library         │               │ :11436 Qwen curator │
└────────────┬─────────────┘               │ :8090  NudeNet      │
             │ move/rename                 └─────────────────────┘
             ▼
   NAS 3D-Prints (Category/Model)
```

Manyfold (separate stack) later **scans** the same NFS path; this container does not call Manyfold APIs.

---

## Quick start

```bash
cd spark-curate
cp .env.example .env
# Edit LIBRARY_HOST_PATH to your mounted 3D-Prints path

docker compose build

# Check Spark reachable from the container network
docker compose run --rm curate smoke

# Dry-run (no moves)
docker compose run --rm curate

# Pilot one category
LIMIT=25 ONLY_CATEGORIES=Cosplay docker compose run --rm curate

# Apply rearrangements
APPLY=1 docker compose run --rm curate
```

### On the Spark host itself

If `3D-Prints` is NFS-mounted on Spark (e.g. `/mnt/3D-Prints`):

```bash
# .env
LIBRARY_HOST_PATH=/mnt/3D-Prints
NETWORK_MODE=host
GEMMA_URL=http://127.0.0.1:11435/v1
CURATOR_URL=http://127.0.0.1:11436/v1
NUDENET_URL=http://127.0.0.1:8090
```

```bash
docker compose build
docker compose run --rm curate smoke
APPLY=1 docker compose run --rm curate
```

### Optional always-on loop (daily)

```bash
# .env
RUN_INTERVAL_SECONDS=86400
APPLY=1
restart: unless-stopped   # set in compose override if desired
docker compose up -d
```

---

## Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `LIBRARY_HOST_PATH` | (required) | Host path bind-mounted to `/library` |
| `APPLY` | `0` | `1` = perform moves |
| `MIN_CONFIDENCE` | `0.55` | Min vision confidence to move |
| `WORKERS` | `2` | Parallel Gemma jobs |
| `LIMIT` | `0` | Max folders (`0` = all) |
| `ONLY_CATEGORIES` | | Comma list e.g. `Cosplay,Anime` |
| `SKIP_GOOD` | `0` | Skip folders with preview not under Unknown |
| `RUN_INTERVAL_SECONDS` | `0` | `0` = once; else sleep loop |
| `GEMMA_URL` | `http://192.168.11.161:11435/v1` | |
| `CURATOR_URL` | `http://192.168.11.161:11436/v1` | |
| `NUDENET_URL` | `http://192.168.11.161:8090` | |

---

## Logs / audit

Written on the library volume (survives container):

```text
/library/.spark-curate/
  decisions-*.jsonl
  audit-*.jsonl
  run-*.log
  summary-*.json
  thumbs/                 # zip-extracted previews (cache only)
```

---

## Safety

| Rule | Behavior |
|------|----------|
| Delete | **Never** |
| Default | Dry-run |
| Name clash | `Model (2)`, `Model (3)`, … |
| No preview | Leave folder in place |
| Low confidence | Leave in place |
| Flagged junk | Leave in place (noted only) |

---

## CLI passthrough

```bash
docker compose run --rm curate --library /library --category Anime --limit 10
docker compose run --rm curate --library /library --apply --min-confidence 0.7
```

---

## After apply

In **Manyfold** (separate app): run library scan / detect filesystem changes so the catalog matches the new tree.

Stop ComfyUI/Wan on Spark while batching Gemma if you hit memory pressure.
