# 3D model library (manyfold-ai)

Self-hosted 3D model library for managing and printing 3D models. Rails 8, Tailwind-only UI, explicit scan pipeline, structured problem detection, merge/unmerge with history.

**Project type:** Web application • **Stack:** Ruby 3.4, Rails 8, Tailwind CSS 4, THREE.js/Mittsu, Sidekiq  
**Source of truth:** `db/schema.rb`, `config/routes.rb`, `app/models/problems/`, `.cursor/rules/`, `.cursor/skills/`

License notices (including upstream MIT copyright) are in [`LICENSE.md`](LICENSE.md) and [`NOTICE`](NOTICE).

---

## What it does

A self-hosted web app that turns folders of 3D model files (STL, 3MF, OBJ, etc.) into a searchable, browsable library. You add **libraries** (root folders on disk); the app scans them, treats each subfolder as a **model**, and stores metadata in a DB. You browse, filter by tags/creators/collections/licenses, view 3D previews, upload files, run **problem detection**, and **merge/unmerge** models. Optional Fediverse (ActivityPub) publishing and multi-user support.

**Who it's for:** Hobbyists and makers with large model collections who want a self-hosted catalog for 3D printing—search, tags, problem checks, and merge tracking without cloud lock-in.

### Capabilities

| Feature | Description |
|--------|-------------|
| Libraries | Add root folders (disk/NAS); scan keeps each subfolder as a model with files |
| Browse/search | Filter by tags, creators, collections; sort, paginate; 3D previews and image carousels |
| Metadata | Edit tags, creators, collections, licenses, links; bulk edit, path templates, README inference |
| Problem detection | Flags issues (empty model, missing file, no license, non-manifold mesh); resolve/ignore from UI |
| Merge/unmerge | Combine models; merge history; undo (unmerge) within configured time window |
| Upload | Web UI upload; TUS for large files |
| Federation | Optional ActivityPub publishing so others can follow your library |
| API | REST-style API, OEmbed, Data Package exports |

**Quick start:** `bin/dev` (local) or `docker compose up` (Docker). App at <http://127.0.0.1:3214>.

---

## Technical overview (for AI and contributors)

### Architecture

- **Rails 8** — Server-rendered HTML, Turbo for interactivity; no XHR/WebSockets for core flows.
- **Sidekiq** — Background jobs: scan, analysis, default, performance, upgrade queues (`config/workers/`, `app/jobs/README.md`).
- **Tailwind CSS 4** — Single entrypoint: `app/assets/stylesheets/tailwind.css`; utilities prefixed `tw:*`.
- **3D** — THREE.js (TypeScript) in browser; Mittsu (Ruby) on server.
- **Database** — PostgreSQL only (production, dev, test, and CI).
- **Problems** — `Problem` model, `Problems::Registry`, category classes in `app/models/problems/`. Resolution only via `Problem.resolve_batch`; creation/clearing only via `Problem.create_or_clear` and Registry detectors.
- **Browse** — Bidirectional row-window infinite scroll on library indexes.

### Key files and locations

| Concern | Location |
|---------|----------|
| Schema | `db/schema.rb` |
| Routes | `config/routes.rb` |
| Problem categories | `app/models/problems/` |
| Phlex components | `app/components/` |
| Scan jobs | `app/jobs/scan/` |
| Architecture guidance | `.cursor/skills/manyfold-*.md` |
| Problems system | `.cursor/skills/problems-system.md` |

### Prerequisites

- Ruby 3.4 (`.ruby-version`), Bundler 2.6+
- Node.js (`.node-version`), `corepack enable`, Yarn 3.8+
- Foreman (or manual process management)
- libarchive, ImageMagick, assimp (3D/archives)
- Optional: ngrok for ActivityPub in dev

### Running locally

```bash
bin/dev
```

App at <http://127.0.0.1:3214>. Config: `.env.development.local` (see `env.example`). For federation in dev, configure an ngrok tunnel or remove it from `Procfile.dev`.

### Running yarn in a container

If you don't have Node/Yarn (e.g. on Windows):

```bash
docker compose --profile assets run --rm assets
```

One-off Tailwind: `docker compose --profile assets run --rm assets yarn build:css:tailwind`.

### CI in a container

CI uses `docker/Dockerfile.ci`. Workflow builds that image, then runs lint and test via `docker run` with repo mounted.

### Devcontainer

VS Code → Remote - Containers → Reopen in Container. Requires Docker and Remote - Containers extension.

### Standards and testing

| Tool | Command |
|------|---------|
| Ruby | `bundle exec standardrb --fix` then `bundle exec rake rubocop` |
| ERB | `bundle exec erb_lint --lint-all` |
| TypeScript | `yarn run lint:ts`, `yarn typecheck` |
| Tests | `bundle exec rspec` (or `bundle exec rake`) |

CI runs on push/PR to `main`: lint first, then test (PostgreSQL).

Doc screenshots: `DOC_SCREENSHOT=true bundle exec rspec` or `-t @documentation`.

### i18n

Rails I18n; `bundle exec i18n-tasks health`. JS: `bundle exec i18n export -c config/i18n-js.yml`.

### Docker

| Scenario | Command |
|----------|---------|
| One-command (Windows) | `.\script\start-docker.ps1` — brings up db, redis, web, worker; generates `db/schema.rb` if missing; waits for `http://localhost:3214/health` |
| Manual | `docker compose build` then `docker compose up -d` — uses `docker/manyfold.dockerfile`, port 3214 |
| Fresh DB schema | `.\script\dump_schema.ps1` (see `db/SCHEMA_DUMP.md`) |
| Test | `docker compose --profile test run --rm test` |

Runs as non-root (PUID/PGID, default 1000:1000). Set env vars to match host if needed. Published image: `ghcr.io/networkbuild3r/manyfold`.

### Configuration

| Variable | Description |
|----------|-------------|
| `SECRET_KEY_BASE` | Required in production |
| `DATABASE_*` / `DATABASE_URL` | DB connection (`config/database.yml`) |
| `REDIS_URL` | Sidekiq and cache |
| `PORT` / `RAILS_PORT` | Server port (default 3214) |
| `WEB_CONCURRENCY` | Puma worker processes (default **0** = single process; raise only if you have RAM) |
| `RAILS_MAX_THREADS` | Puma threads (default **5**) |
| `DEFAULT_WORKER_CONCURRENCY` | Sidekiq default worker threads (default **2**) |
| `PERFORMANCE_WORKER_CONCURRENCY` | Sidekiq performance queue (mesh jobs; default **1**) |
| `MAX_MESH_ANALYSIS_BYTES` | Skip manifold analysis above this size (default **100 MiB**) |
| `SOURCE_REPO` | Git URL for admin version links (default this repository) |
| `USAGE_TRACKING_URL` | Optional; only if you want anonymous usage posts to an endpoint you control |

See `config/database.yml`, `env.example`, and the app settings UI. Use placeholders in examples; never commit real secrets.

### Memory notes (self-hosted)

The app can use a lot of RAM if left on “generous” defaults: large STL digests, mesh analysis, zip downloads, and auto-loading 3D previews on every model card.

Defaults favor stability:

- **Puma** single process / modest threads (`WEB_CONCURRENCY=0`)
- **Sidekiq** lower concurrency so scan/analysis jobs do not stack multi‑GB buffers
- **Streaming** digests and zip packing (no full-file `attachment.read` for those paths)
- **Mesh analysis** size cap + GC after each geometric job
- **3D previews** do not auto-load by default; workers are torn down when cards scroll off-screen

If you have RAM to spare, raise concurrency via the env vars above. For manifold analysis of huge files, raise `MAX_MESH_ANALYSIS_BYTES` or disable **Analyse manifold** in site settings.

---

## Help and support

**Bugs / issues:** Open an issue on this repo.

---

## Contributing

See [CONTRIBUTING.md](.github/CONTRIBUTING.md). Run lint and tests before submitting; CI runs on push/PR.

## License

See [LICENSE.md](LICENSE.md) and [NOTICE](NOTICE).
