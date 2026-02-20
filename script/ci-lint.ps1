# Run the same lint steps as GitHub Actions CI (actionlint + rubocop + erb_lint + yarn).
# Usage: from repo root, .\script\ci-lint.ps1
# Requires: Docker. Ensures push will pass the lint job (run tests separately via docker compose --profile test).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Push-Location $root
try {
    Write-Host "=== 1. Lint workflow files (actionlint) ==="
    docker run --rm -v "${root}:/.repo" -w /.repo rhysd/actionlint:latest
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Host "`n=== 2. Build CI image ==="
    docker build -f docker/Dockerfile.ci -t manyfold-ci:latest -q .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $ws = $root -replace '\\', '/'
    Write-Host "`n=== 3. Run lint in CI image (rubocop, erb_lint, yarn) ==="
    $lintCmd = "corepack enable && bundle config set --local path vendor/bundle && bundle install --quiet && yarn install --silent && yarn build:css:tailwind && bundle exec rake rubocop && bundle exec erb_lint --lint-all && yarn run lint:ts && yarn typecheck && bundle exec i18n-tasks health -l en"
    docker run --rm -v "${ws}:/workspace" -w /workspace manyfold-ci:latest bash -c $lintCmd
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "`nCI lint passed. Push should pass the lint job."
} finally {
    Pop-Location
}
