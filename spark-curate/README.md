# spark-curate

**Standalone Docker service** that reorganizes a 3D-print library into Manyfold-friendly layout:

```text
/library/<Category>/<Model Name>/
```

It is **not** part of the Manyfold web UI, Rails app, or `manyfold` k8s deployment.  
It only needs:

1. A **volume** with your `3D-Prints` tree  
2. Network access to **DGX Spark** (Gemma vision, Qwen curator, NudeNet)

**Never deletes** data — only rearranges via `move`, or queues Manyfold merges. Default is **dry-run**.

---

## Modes

| `MODE` | What it does |
|--------|----------------|
| `organize` (default) | Vision rename/move folders into Category/Model |
| `merge` | Find duplicate packs (`Foo` / `Foo (2)`, shared digests) and queue merges |
| `relocate` | Lift pack roots out of **one** named library dump dest (INIT-025). Default `APPLY=0`. |

**Same character ≠ same model.** Two Batmans stay separate unless structural signals + vision say they are the *same product* (confidence ≥ 0.80).

### Relocate dry-run (`MODE=relocate`, INIT-025/SPEC-003)

In-library lane: lift pack roots out of **one** named dump dest already in the live library. Not Unorg unorganize. Default dry-run.

```bash
# Plan only — never mv (default)
python -m spark_curate --library /library --mode relocate \
  --dest "AnySTL/Girl Sitting on Dinosaur"
# APPLY=1 is SPEC-004 (gated Job) after a human reviews the JSONL.
```

Dest must be a relative `Category/Name` path. Empty, `.`, `/`, `..`, and paths outside the library **fail loud**. Collision with an existing depth-2 folder is `hold` (never `Name (N)`). Sibling dump dests are listed in `relocate-siblings-*.jsonl` and are **not** moved.

Plan line shape (`relocate-plan-*.jsonl`):

```json
{"provenance":"INIT-025/SPEC-003","kind":"lift","source":"/library/AnySTL/Girl Sitting on Dinosaur/Alliance-Stormtrooper_Samurai_NSFW","dest":"AnySTL/Alliance-Stormtrooper_Samurai_NSFW","category":"AnySTL","category_source":"dest_parent","pack_name":"Alliance-Stormtrooper_Samurai_NSFW","status":"lift"}
```

`kind` is `lift` | `hold` | `leftover`. `category_source` is `dest_parent` (first segment of the named dest).


### Merge dry-run / apply

```bash
# Plan only (writes /library/.spark-curate/merges-*.jsonl)
MODE=merge ONLY_CATEGORIES=DC LIMIT=50 docker compose run --rm curate

# Queue approved pairs (confidence >= 0.80) into merges-pending.jsonl
MODE=merge APPLY=1 ONLY_CATEGORIES=DC LIMIT=50 docker compose run --rm curate
```

Then in Manyfold (same NFS at `/models`):

```bash
# Preview
DRY_RUN=1 bundle exec rake manyfold:apply_spark_merges
# Apply Model#merge! (undo via MergeHistory for 30 days)
bundle exec rake manyfold:apply_spark_merges
```

Cluster:

```bash
kubectl create job -n manyfold spark-curate-merge --from=cronjob/spark-curate
kubectl set env job/spark-curate-merge -n manyfold MODE=merge APPLY=0 ONLY_CATEGORIES=DC LIMIT=50
# After reviewing plans:
kubectl set env job/spark-curate-merge -n manyfold APPLY=1   # or new job
kubectl exec -n manyfold deploy/manyfold -- env DRY_RUN=1 bundle exec rake manyfold:apply_spark_merges
kubectl exec -n manyfold deploy/manyfold -- bundle exec rake manyfold:apply_spark_merges
```

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
| `APPLY` | `0` | `1` = perform moves / queue merges. Relocate stays `0` until SPEC-004. |
| `MODE` | `organize` | `organize`, `merge`, `relocate`, … |
| `DEST` | | Relative `Category/Name` for `MODE=relocate` |
| `MIN_CONFIDENCE` | `0.55` | Min vision confidence to move (organize) |
| `MIN_MERGE_CONFIDENCE` | `0.80` | Min confidence to queue merge for Manyfold |
| `MAX_MERGE_PAIRS` | `200` | Cap merge candidate pairs per run |
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
  merges-*.jsonl          # merge mode plans
  merges-pending.jsonl    # approved for Manyfold apply
  merges-applied.jsonl
  merges-failed.jsonl
  relocate-plan-*.jsonl      # MODE=relocate: lift | hold | leftover (INIT-025/SPEC-003)
  relocate-siblings-*.jsonl  # other organize-applied dump dests; inventory only
  relocate-summary-*.json
  thumbs/                 # zip-extracted previews (cache only)
```

---

## Safety

| Rule | Behavior |
|------|----------|
| Delete | **Never** |
| Default | Dry-run |
| Name clash (organize) | `Model (2)`, `Model (3)`, … |
| Name clash (relocate) | **`hold`** — never `Name (N)` |
| No preview | Leave folder in place |
| Low confidence | Leave in place |
| Flagged junk | Leave in place (noted only) |
| Merge franchise-only | Forced `keep_separate` |
| Merge confidence &lt; 0.80 | Plan only; never queue pending |

---

## CLI passthrough

```bash
docker compose run --rm curate --library /library --category Anime --limit 10
docker compose run --rm curate --library /library --apply --min-confidence 0.7
docker compose run --rm curate --mode merge --category DC --limit 50
docker compose run --rm curate --mode merge --apply --min-merge-confidence 0.80
```

---

## After apply

In **Manyfold** (separate app): run library scan / detect filesystem changes so the catalog matches the new tree.

Stop ComfyUI/Wan on Spark while batching Gemma if you hit memory pressure.
