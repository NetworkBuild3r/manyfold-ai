# Generate db/schema.rb by running migrations against PostgreSQL in Docker.
# Run from project root. Requires Docker Desktop (or Docker daemon) to be running.
$ErrorActionPreference = "Stop"
Write-Host "Starting db and redis (if not already up)..."
docker compose up -d db redis
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Waiting for PostgreSQL..."
Start-Sleep -Seconds 3
Write-Host "Running db:create db:migrate db:schema:dump in test container (writes to mounted repo)..."
docker compose --profile test run --rm -e SKIP_MIGRATIONS=1 test sh -c "bundle exec rails db:create db:migrate db:schema:dump"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Generated db/schema.rb. Commit it so the app container can start on a fresh database."
