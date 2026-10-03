# Forge report site

`forge report site` turns SPEC-009 JSON reports into a static HTML site. No
database. No CDN. The page answers **What do I actually have** and lists
cross-pack duplicate pairs.

Provenance: `INIT-032/SPEC-014`. Input contract: `docs/reports.md` (`schema_version` 1).

## CLI

```text
forge report site --in DIR --out DIR
```

| Flag | Meaning |
|---|---|
| `--in DIR` | directory with `inventory.json` and/or `duplicates.json` |
| `--out DIR` | destination; created if missing |

Exit `2` when `--in` is missing, neither JSON file is present, JSON is
malformed, or `schema_version` is not `1`.

```bash
forge report inventory  --format json --out /reports
forge report duplicates --format json --out /reports --min-copies 2 --limit 0
forge report site --in /reports --out /reports/site
```

## Output

```text
OUT/
  index.html              overview headline
  inventory.html          catalog tables
  duplicates.html         pair table shell (JS loads chunks)
  assets/site.css
  assets/site.js
  data/pairs/meta.json    chunkSize, chunkCount, pairCount
  data/pairs/index.json   interned pack names + compact rows (loaded on filter)
  data/pairs/c0000.json   first 250 pairs (includes shared[] for expand)
  data/pairs/c0001.json
```

The first paint is HTML + CSS + JS + `meta.json` + `c0000.json` (under 1 MiB
even with tens of thousands of pairs). Further chunks load on Next / filter.

## Security

Every dynamic string is `html.escape(..., quote=True)`. A filename containing
`<script>` is text, not a tag.

Every HTML page has

```html
<meta http-equiv="Content-Security-Policy" content="default-src 'self'">
```

Scripts and styles are external files. There is no `'unsafe-inline'`. The
nginx Deployment also sends `Content-Security-Policy: default-src 'self'`.

## Cluster

Served at `https://forge.ibhacked.us` (oauth2-proxy, TLS secret `ibhacked-tls`
in `manyfold`). The on-demand Job template lives in gitops:

`home_k3/apps/manyfold/manifests/forge/site/templates/`

Do not run the Job while `forge-sweep` is filling the catalog — the report
queries are heavy aggregates on the shared Postgres.
