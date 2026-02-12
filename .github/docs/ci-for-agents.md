# CI for agents and contributors

This doc describes how to run the same checks as CI locally and how to trigger CI on demand so code stays bug-free before merge.

## Triggering CI from GitHub

- **Automatic**: Push or open a PR targeting `main`. The **CI** workflow runs (lint first, then test).
- **Manual**: Actions → **CI** → **Run workflow**, choose branch, Run. Use this to verify a branch without opening a PR (e.g. after an agent or human makes changes).

Required status checks for merging are the **lint** and **test** jobs from the CI workflow.

## Local commands (match CI)

Run these after `bundle install` and `yarn install` (or use the setup composite’s equivalent). Order matches CI: lint first, then test.

**Lint (fast, run first):**

```bash
bundle exec rake rubocop
bundle exec erb_lint --lint-all
yarn run lint:ts
yarn typecheck
```

**Test (needs DB and Redis):**

```bash
export RAILS_ENV=test
# Set DATABASE_URL for your DB (e.g. postgresql://... or sqlite3:/tmp/test.db)
bundle exec rails db:prepare:with_data
bundle exec rails assets:precompile
bundle exec rspec --fail-fast
```

Or use the default dev DB for a quick run: `bundle exec rspec --fail-fast` (ensure DB is created and migrated).

### Windows (PowerShell)

Windows doesn't run `bin/rails` or `bin/bundle` via the shebang, so use `ruby bin/...` or the script below.

**One-liner test run (from repo root):**

```powershell
powershell -ExecutionPolicy Bypass -File script/run-tests.ps1
```

**Or run steps yourself (from repo root):**

```powershell
$env:RAILS_ENV = "test"
ruby bin/rails db:prepare:with_data
ruby bin/rails assets:precompile
ruby bin/bundle exec rspec --fail-fast
```

Lint with Ruby explicitly: `ruby bin/bundle exec rake rubocop`, then `ruby bin/bundle exec erb_lint --lint-all`, then `yarn run lint:ts`, `yarn typecheck`.

## Pipeline layout (DRY)

- **`.github/workflows/ci.yml`** – Single entry: runs **lint** then **test** (test needs lint). `workflow_dispatch` enables on-demand runs.
- **`.github/actions/setup/`** – Ruby, Node, gems, yarn (used by CI and other workflows).
- **`.github/actions/lint/`** – Ruby (Rubocop), ERB, TypeScript lint and typecheck.
- **`.github/actions/run-tests/`** – DB prepare, assets, RSpec (caller provides `DATABASE_URL` and services).

Other workflows (Docker, CodeQL, i18n, OpenAPI, translation) reuse **setup** where applicable; they do not run the full lint/test suite.
