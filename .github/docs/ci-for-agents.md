# CI for agents and contributors

This doc describes how to run the same checks as CI locally and how to trigger CI on demand so code stays bug-free before merge.

## Before you push (avoid failed CI)

To run **the same lint steps as the CI workflow** (actionlint + rubocop + erb_lint + TypeScript), use the script that uses the CI image:

**Windows (PowerShell, from repo root):**

```powershell
.\script\ci-lint.ps1
```

This runs actionlint, builds `docker/Dockerfile.ci`, then runs rubocop, erb_lint, `yarn run lint:ts`, `yarn typecheck`, and `bundle exec i18n-tasks health -l en` inside that image. If it passes, the **lint** job on GitHub will pass. Run tests separately (e.g. `docker compose --profile test run --rm test`) or rely on CI for the test matrix.

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
bundle exec i18n-tasks health -l en
```

**Test (needs DB and Redis):**

```bash
export RAILS_ENV=test
# Set DATABASE_URL for your DB (e.g. postgresql://... or sqlite3:/tmp/test.db)
bundle exec rails db:prepare:with_data
bundle exec rails assets:precompile
bundle exec rspec --fail-fast
```

CI runs the test suite against **PostgreSQL only**. The app’s `db/schema.rb` is generated from PostgreSQL; MySQL and SQLite are in the Gemfile for local use but are not exercised in CI.

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

Lint with Ruby explicitly: `ruby bin/bundle exec rake rubocop`, then `ruby bin/bundle exec erb_lint --lint-all`, then `yarn run lint:ts`, `yarn typecheck`, then `ruby bin/bundle exec i18n-tasks health -l en`.

## Why local CI can miss things

Local commands above cover **Ruby, ERB, TypeScript, and RSpec** only. They do **not** run:

- **Workflow validation** — `.github/workflows/*.yml` are not checked locally. Errors like invalid `${{ }}` expressions (e.g. `secrets` in an `if` condition, which GitHub rejects) only appear when the workflow runs on GitHub. **CI now runs [actionlint](https://github.com/rhysd/actionlint)** in the lint job so workflow syntax and expression semantics are validated before lint/test. When you change any workflow file, run actionlint locally to catch issues early:
  ```bash
  # Install once: go install github.com/rhysd/actionlint/cmd/actionlint@latest
  actionlint
  ```
  Or use the [online playground](https://rhysd.github.io/actionlint/).
- **Database** — CI runs tests against PostgreSQL only. To match CI locally, use PostgreSQL (e.g. `docker compose --profile test run --rm test`) or set `DATABASE_URL` to the same postgres URL as in `ci.yml`.
- **Other workflows** — `docker.yml`, `codeql.yml`, `i18n_health.yml`, `openapi.yml`, `translation.yml`, `auto_merge.yml` are not exercised by the local lint/test commands. The main **CI** workflow now includes `i18n-tasks health -l en` in the lint job, so translation issues are caught before merge; the separate **Check translations** workflow still runs on PRs to `main`. Changing other workflows should be validated with actionlint and by triggering the corresponding workflow manually (Actions → workflow name → Run workflow).

Before pushing, run lint and tests as in [Local commands](#local-commands-match-ci); if you changed any file under `.github/workflows/`, run `actionlint` as well.

## Pipeline layout (DRY)

- **`.github/workflows/ci.yml`** – Runs **workflow lint (actionlint)** then **lint** then **test** inside a container. Builds `docker/Dockerfile.ci`, then runs actionlint, then lint and test via `docker run` with the workspace mounted. `workflow_dispatch` enables on-demand runs.
- **`docker/Dockerfile.ci`** – CI image (Ruby 3.4, Node 24, Yarn, system deps). Used so CI does not depend on the host’s Ruby/Node; same checks can be run locally via Docker.
- **`.github/actions/setup/`** – Ruby, Node, gems, yarn (used by other workflows that do not use the CI container).
- **`.github/actions/lint/`** – Ruby (Rubocop), ERB, TypeScript lint and typecheck.
- **`.github/actions/run-tests/`** – DB prepare, assets, RSpec (caller provides `DATABASE_URL` and services).

Other workflows (Docker, CodeQL, i18n, OpenAPI, translation) reuse **setup** where applicable; they do not run the full lint/test suite.
