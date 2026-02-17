# Manyfold

Self-hosted 3D model library for managing and printing 3D models, with a batched scan pipeline, Tailwind-based UI, and structured problem detection and merge/unmerge.

This repository is a fork of [manyfold3d/manyfold](https://github.com/manyfold3d/manyfold), maintained independently.

## What is Manyfold?

**Manyfold** is a **self-hosted web application** that turns a pile of 3D model files on your disk (or NAS) into a searchable, browsable library. You run it on your own server or machine; your files stay on your storage. There is no mandatory cloud or paid service—you point the app at folders on your filesystem, it scans them, and you manage everything through a browser.

**What you use it for:** You have (or will have) lots of 3D models—STL, 3MF, OBJ, etc.—for 3D printing, sharing, or archiving. Instead of digging through folders by hand, you add **libraries** (root folders on disk). Manyfold scans those folders, treats each subfolder as a **model**, and keeps metadata in a database. You can then browse and filter by **tags**, **creators**, **collections**, and **licenses**; view 3D previews in the browser; upload new files; and run **problem detection** (e.g. missing license, empty model, bad file names). The app can also **merge** models, track **merge history**, and optionally **undo** a merge within a time window. In multi-user setups it supports roles and permissions; it can also publish to the **Fediverse** (ActivityPub) so others can follow your library or collections.

**Who it’s for:** Hobbyists and makers with large model collections, people who want a private or shared catalog for 3D printing, and anyone who prefers to self-host rather than rely on a third-party catalog or cloud. If you’ve outgrown “a folder full of STLs” and want search, tags, and problem checks without sending data to someone else’s server, Manyfold is built for that.

**In short:** Manyfold is “your own 3D model library and catalog in a browser,” with scanning, tagging, problem detection, merge/unmerge, and optional federation—all under your control.

### What you can do with it

- **Libraries** — Add one or more root folders (on disk or mounted storage); the app scans them and keeps each subfolder as a **model** with its files.
- **Browse and search** — Filter models by tags, creators, collections, libraries; sort and paginate; view 3D previews and image carousels in the browser.
- **Metadata and organization** — Edit tags, creators, collections, licenses, and links per model; bulk edit across many models; use path templates and README files to infer metadata.
- **Problem detection** — The app flags issues (e.g. empty model, missing file, no license, no tags, non-manifold mesh) and lets you resolve or ignore them from the UI.
- **Merge and unmerge** — Combine several models into one; merges are recorded so you can **undo** (unmerge) within a configured time window.
- **Upload** — Upload new files or whole models via the web UI (TUS for large files).
- **Federation (optional)** — Publish models and collections to the Fediverse so others can follow and discover your library via ActivityPub.
- **API and exports** — REST-style API, OEmbed, Data Package exports, and integration points for automation.

To run the app yourself, use **Docker** (`docker compose up`) or run it locally with **bin/dev**; both are described in the [Developer documentation](#developer-documentation) below.

## Technical overview

This project is built with the following approach (for contributors and integrators):

- **Scanning** — Scan flow is explicit and batched: filesystem detection → create model from path → add new files → parse metadata → a single finalize step that runs problem checks. No cascade triggers from `touch` on models/files, so DB–filesystem sync stays predictable. Problem detection uses a **Registry** and category classes; jobs call `Problem.create_or_clear` only via those detectors.
- **Problems system** — One entry point for resolution (`Problem.resolve_batch`), strategy classes under `app/models/problems/`, and Turbo Stream responses that send a single document (removes + optional card replace). Resolve/ignore only through that path.
- **Data management** — Model **merge** with **merge history** and a time-limited **unmerge** (undo) so merges can be reverted within a configured window.
- **UI** — **Tailwind-only** (no Bootstrap, Bootswatch, or Sass). One pipeline: `app/assets/stylesheets/tailwind.css` → `app/assets/builds/tailwind.css`. Light/dark themes, ViewComponent-based components.
- **CI and quality** — Lint (StandardRB, Rubocop, erb_lint, TypeScript, Tailwind) then RSpec; multi-DB CI (PostgreSQL, MySQL, SQLite); Docker build and smoke test.

## Help and support

- **Bugs / issues:** Open an issue on this repo.

---

## Developer documentation

*For contributors who want to run and develop this project.*

### Architecture (summary)

- **Rails 8** — Server-rendered HTML, Turbo for interactivity; no XHR/WebSockets for core flows.
- **Sidekiq** — Background jobs: scan, analysis, default, performance, upgrade queues (see `config/workers/` and `app/jobs/README.md`).
- **Tailwind CSS 4** — Single entrypoint: `app/assets/stylesheets/tailwind.css`; utilities prefixed `tw:*`.
- **3D** — **THREE.js** (TypeScript) in the browser; **Mittsu** (Ruby) on the server.
- **Database** — PostgreSQL in production; SQLite supported in dev/test; MySQL in CI.
- **Problems** — `Problem` model, `Problems::Registry`, category classes in `app/models/problems/`. Resolution only via `Problem.resolve_batch`; creation/clearing only via `Problem.create_or_clear` and Registry-registered detectors.

### Prerequisites

- **Ruby** 3.4 (see `.ruby-version`)
- **Bundler** 2.6+
- **Node.js** (see `.node-version`), **corepack enable**, **Yarn** 3.8+
- **Foreman** (or run processes manually)
- **libarchive**, **ImageMagick**, **assimp** (for 3D/archives)
- Optional: **ngrok** for ActivityPub in dev

### Running locally

```bash
bin/dev
```

App at <http://127.0.0.1:3214>. Optional config: `.env.development.local` (see `env.example`). For federation in dev, configure an ngrok tunnel named `manyfold` or remove the ngrok line from `Procfile.dev`.

### Running yarn in a container

If you don’t have Node or Yarn installed (e.g. on Windows), you can build JS and CSS inside a container:

```bash
docker compose --profile assets run --rm assets
```

That runs `bundle install`, `yarn install`, and `yarn build`. For one-off commands (e.g. only Tailwind): `docker compose --profile assets run --rm assets yarn build:css:tailwind`.

### CI in a container

CI (lint and test) runs inside a Docker image built from `docker/Dockerfile.ci`. The workflow builds that image, then runs lint and test via `docker run` with the repo mounted, so the same environment can be reproduced locally.

### Devcontainer

Open the repo in VS Code and use **Remote - Containers: Reopen in Container**. Requires Docker and the Remote - Containers extension.

### Standards and testing

- **Ruby:** `bundle exec standardrb --fix` then `bundle exec rake rubocop` (or `bundle exec rubocop`) if needed.
- **ERB:** `bundle exec erb_lint --lint-all`.
- **TypeScript:** `yarn run lint:ts`, `yarn typecheck`.
- **Tests:** `bundle exec rspec` (or `bundle exec rake`). CI runs on push/PR to `main` (lint first, then test matrix with PostgreSQL, MySQL, SQLite).

Documentation screenshots: `DOC_SCREENSHOT=true bundle exec rspec` (or `-t @documentation`).

### i18n

Rails I18n; check with `bundle exec i18n-tasks health`. JS translations: `bundle exec i18n export -c config/i18n-js.yml`. Translation.io for other languages; sync: `rake translation:clobber_and_sync:{locale}`.

### Docker

- **One-command startup (Windows):** Start Docker Desktop, then from the repo root run `.\script\start-docker.ps1`. This brings up db, redis, web, and worker; generates `db/schema.rb` if missing; and waits for `http://localhost:3214/health` to succeed.
- **Multi-container (manual):** `docker compose build` then `docker compose up -d`. Uses `docker/manyfold.dockerfile` for web and workers. Port 3214; see `docker-compose.yml` and optional `LIBRARY_MOUNT`. On a fresh DB, generate `db/schema.rb` first with `.\script\dump_schema.ps1` (see `db/SCHEMA_DUMP.md`).
- **Test in Docker:** `docker compose --profile test run --rm test`.

The app runs as a non-root user (PUID/PGID, default 1000:1000); set these env vars to match your host if needed. The container will not run as root (PUID=0).

### Configuration

| Variable | Description |
|----------|-------------|
| `SECRET_KEY_BASE` | Required in production; use a long random value. |
| `DATABASE_*` / `DATABASE_URL` | DB connection (see `config/database.yml`). |
| `REDIS_URL` | Redis for Sidekiq and cache. |
| `PORT` / `RAILS_PORT` | Server port (default 3214 in dev). |

See `config/database.yml`, `env.example`, and the app’s settings UI for more options (multiuser, federation, etc.). In examples, use placeholders (e.g. `YOUR_SECRET_KEY_BASE`) and never commit real secrets.

---

## Contributing

See [CONTRIBUTING.md](.github/CONTRIBUTING.md). Run lint and the test suite before submitting; CI will run on push/PR.

## License

See [LICENSE.md](LICENSE.md) in this repo.

