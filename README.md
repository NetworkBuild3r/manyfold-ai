# Manyfold

Self-hosted 3D model library for managing and printing 3D models. Rails 8, Tailwind-only UI, batched scan pipeline, structured problem detection, merge/unmerge with history.

**Project type:** Web application • **Stack:** Ruby 3.4, Rails 8, Tailwind CSS 4, THREE.js/Mittsu, Sidekiq  
**Source of truth:** `db/schema.rb`, `config/routes.rb`, `app/models/problems/`, `.cursor/rules/`, `.cursor/skills/`

## Fork status

This repo is a fork of [manyfold3d/manyfold](https://github.com/manyfold3d/manyfold), maintained independently. See [Differences from upstream](#differences-from-upstream) below.

---

## What is Manyfold?

**Manyfold** is a self-hosted web app that turns folders of 3D model files (STL, 3MF, OBJ, etc.) into a searchable, browsable library. You add **libraries** (root folders on disk); the app scans them, treats each subfolder as a **model**, and stores metadata in a DB. You browse, filter by tags/creators/collections/licenses, view 3D previews, upload files, run **problem detection**, and **merge/unmerge** models. Optional Fediverse (ActivityPub) publishing and multi-user support.

**Who it's for:** Hobbyists and makers with large model collections who want a self-hosted catalog for 3D printing—search, tags, problem checks, and merge tracking without cloud lock-in.

### Capabilities

| Feature | Description |
|--------|-------------|
| Libraries | Add root folders (disk/NAS); scan keeps each subfolder as a model with files |
| Browse/search | Filter by tags, creators, collections; sort, paginate; 3D previews and image carousels |
| Metadata | Edit tags, creators, collections, licenses, links; bulk edit; path templates, README inference |
| Problem detection | Flags issues (empty model, missing file, no license, non-manifold mesh); resolve/ignore from UI |
| Merge/unmerge | Combine models; merge history; undo (unmerge) within configured time window |
| Upload | Web UI upload; TUS for large files |
| Federation | Optional ActivityPub publishing so others can follow your library |
| API | REST-style API, OEmbed, Data Package exports |

**Quick start:** `bin/dev` (local) or `docker compose up` (Docker). App at <http://127.0.0.1:3214>.

---

## Differences from upstream

This fork diverges from [manyfold3d/manyfold](https://github.com/manyfold3d/manyfold) with a different architecture and UX approach:

| Aspect | Upstream (manyfold3d) | This fork |
|--------|------------------------|-----------|
| UI | Bootstrap 5 | **Tailwind-only** (no Bootstrap/Bootswatch/Sass). Single pipeline: `app/assets/stylesheets/tailwind.css` → `app/assets/builds/tailwind.css`. Light/dark themes. |
| Scanning | Implicit/cascade | **Explicit batched pipeline**: filesystem detection → create model from path → add files → parse metadata → single finalize step. No `touch`-driven cascades; DB–filesystem sync is predictable. |
| Problems | Various entry points | **Single entry point**: `Problem.resolve_batch`. Strategy classes in `app/models/problems/`. Turbo Stream responses (removes + optional card replace). Creation/clearing only via `Problem.create_or_clear` and Registry-registered detectors. |
| Data management | Basic merge | **Merge with history** and time-limited unmerge; path prefix tracking; `db_integrity.rake` for integrity constraints. |
| Components | ViewComponent + ERB | **Phlex**-based components in `app/components/`; shared `_problems_card.html.erb`; model card refactored (ModelCardActions, ModelCardPreview, DropdownMenu). |
| Selection/browsing | — | **Base and file-list selection** Stimulus controllers; infinite scroll restore; `ModelListRestoreWrapper`. |
| CI | Single-DB | **Multi-DB CI** (PostgreSQL, MySQL, SQLite); lint (StandardRB, Rubocop, erb_lint, TypeScript, Tailwind) then RSpec. |
| Docker | `docker/default.dockerfile` | `docker/manyfold.dockerfile`; Windows one-command: `.\script\start-docker.ps1`. |
| Docs | Links to manyfold.app | **Fork-first README**; `.cursor/rules/` and `.cursor/skills/` for AI-assisted development. |

**Why this approach:** Fewer hidden side effects, clearer contracts, better AI/contributor onboarding, and consistent Tailwind-first design.

---

## Technical overview (for AI and contributors)

### Architecture

- **Rails 8** — Server-rendered HTML, Turbo for interactivity; no XHR/WebSockets for core flows.
- **Sidekiq** — Background jobs: scan, analysis, default, performance, upgrade queues (`config/workers/`, `app/jobs/README.md`).
- **Tailwind CSS 4** — Single entrypoint: `app/assets/stylesheets/tailwind.css`; utilities prefixed `tw:*`.
- **3D** — THREE.js (TypeScript) in browser; Mittsu (Ruby) on server.
- **Database** — PostgreSQL in production; SQLite in dev/test; MySQL in CI.
- **Problems** — `Problem` model, `Problems::Registry`, category classes in `app/models/problems/`. Resolution only via `Problem.resolve_batch`; creation/clearing only via `Problem.create_or_clear` and Registry detectors.

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

App at <http://127.0.0.1:3214>. Config: `.env.development.local` (see `env.example`). For federation in dev, configure ngrok tunnel `manyfold` or remove it from `Procfile.dev`.

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

CI runs on push/PR to `main`: lint first, then test matrix (PostgreSQL, MySQL, SQLite).

Doc screenshots: `DOC_SCREENSHOT=true bundle exec rspec` or `-t @documentation`.

### i18n

Rails I18n; `bundle exec i18n-tasks health`. JS: `bundle exec i18n export -c config/i18n-js.yml`. Translation.io: `rake translation:clobber_and_sync:{locale}`.

### Docker

| Scenario | Command |
|----------|---------|
| One-command (Windows) | `.\script\start-docker.ps1` — brings up db, redis, web, worker; generates `db/schema.rb` if missing; waits for `http://localhost:3214/health` |
| Manual | `docker compose build` then `docker compose up -d` — uses `docker/manyfold.dockerfile`, port 3214 |
| Fresh DB schema | `.\script\dump_schema.ps1` (see `db/SCHEMA_DUMP.md`) |
| Test | `docker compose --profile test run --rm test` |

Runs as non-root (PUID/PGID, default 1000:1000). Set env vars to match host if needed.

### Configuration

| Variable | Description |
|----------|-------------|
| `SECRET_KEY_BASE` | Required in production |
| `DATABASE_*` / `DATABASE_URL` | DB connection (`config/database.yml`) |
| `REDIS_URL` | Sidekiq and cache |
| `PORT` / `RAILS_PORT` | Server port (default 3214) |

See `config/database.yml`, `env.example`, and the app settings UI. Use placeholders in examples; never commit real secrets.

---

## Help and support

**Bugs / issues:** Open an issue on this repo.

---

## Contributing

See [CONTRIBUTING.md](.github/CONTRIBUTING.md). Run lint and tests before submitting; CI runs on push/PR.

## License

See [LICENSE.md](LICENSE.md).
