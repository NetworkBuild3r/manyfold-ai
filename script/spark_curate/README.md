# Moved: standalone Docker service

This tool is **not** part of the Manyfold UI.

**Canonical project:** [`../../spark-curate/`](../../spark-curate/)

```bash
cd spark-curate
cp .env.example .env
docker compose build
docker compose run --rm curate smoke
docker compose run --rm curate          # dry-run
APPLY=1 docker compose run --rm curate  # rearrange only (never deletes)
```

See `spark-curate/README.md` for full docs.
