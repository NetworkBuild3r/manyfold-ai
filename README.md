# Manyfold (this fork)

Manyfold is an open source, self-hosted web app for managing a collection of 3D models, with a focus on 3D printing. The official project lives at [manyfold.app](https://manyfold.app/) and [manyfold3d/manyfold](https://github.com/manyfold3d/manyfold).

## How this fork is different

This fork is **forward-thinking and moves fast**. We welcome **VIBE coding** and AI-assisted development: we ship fixes and improvements faster than upstream can handle, and we’re not shy about modernizing the stack and cleaning up tech debt.

- **Tailwind-only UI** — Bootstrap, Bootswatch, and Sass are gone. One `tailwind.css` pipeline, light/dark themes, and a simpler frontend.
- **CI and tests** — Lint (Ruby, ERB, TypeScript, Tailwind) and RSpec with a stable DB strategy (e.g. deletion in CI/Docker to avoid deadlocks).
- **Aligned with upstream where it matters** — Same app, same features; we just iterate and fix more aggressively.

If you want the official, conservative Manyfold experience, use the [main repo](https://github.com/manyfold3d/manyfold) and [manyfold.app](https://manyfold.app/). If you want to hack, experiment, and ship — this fork is for you.

## Help and support

- **Bugs / issues:** [GitHub issues](https://github.com/manyfold3d/manyfold/issues/new) (upstream) or open one on this repo.
- **Chat:** [Matrix #manyfold:matrix.org](https://matrix.to/#/#manyfold:matrix.org).
- **Fediverse:** [@manyfold](https://3dp.chat/@manyfold).

[<img src="https://opencollective.com/manyfold/donate/button@2x.png?color=blue" alt="Donate with OpenCollective" width="20%" />](https://opencollective.com/manyfold/donate) — supports the upstream project.

---

## Developer documentation

*For contributors who want to run and develop this fork.*

### Architecture

- **Rails** (server-rendered, standard HTTP; no XHR/WebSockets yet).
- **Sidekiq** for background jobs.
- **Tailwind CSS** for styles (no Bootstrap). Single pipeline: `app/assets/stylesheets/tailwind.css` → `app/assets/builds/tailwind.css`.
- **THREE.js** (TypeScript) for client 3D; **Mittsu** (Ruby) for server-side 3D.
- **PostgreSQL** in production; SQLite in dev.

### Running locally

**Requirements:** Ruby 3.4, Bundler 2.6+, Node.js (see `.node-version`), `corepack enable`, Yarn 3.8+, Foreman (or similar), libarchive, ImageMagick, assimp. Optional: ngrok for ActivityPub.

```bash
bin/dev
```

App at <http://127.0.0.1:3214>. Optional config: `.env.development.local` (see `env.example`). For ngrok, configure a tunnel named `manyfold` or remove it from `Procfile.dev` if you don’t need federation in dev.

### Devcontainer

VS Code + Remote - Containers: open repo → “Reopen in Container”. Prerequisites: Docker, VS Code with Remote - Containers extension.

### Standards and testing

- **Ruby:** StandardRB + Rubocop → `bundle exec rake rubocop` or `bundle exec standardrb --fix`.
- **ERB:** `bundle exec erb_lint --lint-all`.
- **TypeScript:** `yarn run lint:ts`, `yarn typecheck`.
- **Tests:** `bundle exec rspec` (or `bundle exec rake`). CI runs on push/PR via GitHub Actions.

Screenshots for docs: `DOC_SCREENSHOT=true bundle exec rspec` (or `-t @documentation`).

### i18n

Rails I18n; check with `bundle exec i18n-tasks health`. JS translations: `bundle exec i18n export -c config/i18n-js.yml`. Translation.io for other languages; sync: `rake translation:clobber_and_sync:{locale}`.

### Docker

Multi-platform image (see [manyfold.app Docker instructions](https://manyfold.app/get-started/docker)). Build: `docker build -f docker/default.dockerfile .` (or use this repo’s `docker/manyfold-solo.dockerfile` / `docker-compose.yml` for local/test).

---

## Funding (upstream)

Manyfold is funded by [NGI0 Entrust](https://nlnet.nl/entrust) and by [donations on OpenCollective](https://opencollective.com/manyfold/donate).

[<img src="https://nlnet.nl/logo/banner.png" alt="NLnet foundation logo" width="20%" />](https://nlnet.nl)  
[<img src="https://nlnet.nl/image/logos/NGI0_tag.svg" alt="NGI Zero Logo" width="20%" />](https://nlnet.nl/entrust)
