# Run test suite (matches CI). Use this on Windows when .\bin\rails prompts for an app.
# From repo root: powershell -ExecutionPolicy Bypass -File script/run-tests.ps1
$ErrorActionPreference = "Stop"
$env:RAILS_ENV = "test"

Push-Location $PSScriptRoot\..
try {
    Write-Host "Preparing test database..."
    ruby bin/rails db:prepare:with_data
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "Compiling assets..."
    ruby bin/rails assets:precompile
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Write-Host "Running RSpec..."
    ruby bin/bundle exec rspec --fail-fast
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
