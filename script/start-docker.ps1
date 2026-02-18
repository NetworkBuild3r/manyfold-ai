# Bootstrap full Docker stack: db, redis, schema dump (if needed), web, worker.
# Run from repo root.
#
# Prerequisite: Start Docker Desktop (or your Docker daemon) before running.
# Usage: .\script\start-docker.ps1
#
# If you see "The system cannot find the file specified" for dockerDesktopLinuxEngine,
# Docker Desktop is not running—start it and run this script again.

$ErrorActionPreference = "Stop"

function Test-Docker {
  docker compose version 2>$null
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker is not running or not in PATH. Start Docker Desktop and run this script again." -ForegroundColor Red
    exit 1
  }
}

function Wait-ForDb {
  param([int]$MaxWaitSeconds = 60)
  $elapsed = 0
  while ($elapsed -lt $MaxWaitSeconds) {
    $out = docker compose exec -T db pg_isready -U manyfold -d manyfold 2>$null
    if ($LASTEXITCODE -eq 0) { return $true }
    Start-Sleep -Seconds 3
    $elapsed += 3
  }
  return $false
}

function Wait-ForWebHealth {
  param([int]$MaxWaitSeconds = 120)
  $elapsed = 0
  while ($elapsed -lt $MaxWaitSeconds) {
    try {
      $r = Invoke-WebRequest -Uri "http://localhost:3214/health" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
      if ($r.StatusCode -eq 200) { return $true }
    } catch { }
    Start-Sleep -Seconds 5
    $elapsed += 5
  }
  return $false
}

Write-Host "Checking Docker..." -ForegroundColor Cyan
Test-Docker

Write-Host "Starting db and redis..." -ForegroundColor Cyan
docker compose up -d db redis
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Waiting for PostgreSQL..." -ForegroundColor Cyan
Start-Sleep -Seconds 3
$dbReady = Wait-ForDb -MaxWaitSeconds 45
if (-not $dbReady) {
  Write-Host "PostgreSQL did not become ready. Check: docker compose logs db" -ForegroundColor Red
  exit 1
}

# Generate schema.rb if missing so fresh DB boots without running 128+ schema migrations
if (-not (Test-Path "db/schema.rb")) {
  Write-Host "db/schema.rb not found. Generating via test container (this may take a few minutes)..." -ForegroundColor Cyan
  docker compose --profile test run --rm -e SKIP_MIGRATIONS=1 test sh -c "bundle exec rails db:create db:migrate db:schema:dump"
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Schema dump failed. Check: docker compose --profile test run --rm test sh -c 'bundle exec rails db:create db:migrate db:schema:dump'" -ForegroundColor Red
    exit 1
  }
  Write-Host "Generated db/schema.rb" -ForegroundColor Green
} else {
  Write-Host "db/schema.rb present, skipping schema dump" -ForegroundColor Gray
}

Write-Host "Building web and worker images (if needed)..." -ForegroundColor Cyan
docker compose build web worker 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Starting web and worker..." -ForegroundColor Cyan
docker compose up -d web worker
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Waiting for web /health (up to 2 minutes)..." -ForegroundColor Cyan
$webHealthy = Wait-ForWebHealth -MaxWaitSeconds 120
if (-not $webHealthy) {
  Write-Host "Web did not respond with 200 OK. Showing last 60 lines of web logs:" -ForegroundColor Yellow
  docker compose logs web --tail 60
  Write-Host "Check full logs: docker compose logs -f web" -ForegroundColor Yellow
  exit 1
}

Write-Host ""
Write-Host "Stack is up." -ForegroundColor Green
Write-Host "  Web:    http://localhost:3214" -ForegroundColor White
Write-Host "  Health: http://localhost:3214/health" -ForegroundColor White
Write-Host "  Logs:   docker compose logs -f web" -ForegroundColor White
Write-Host ""

# Quick health check
try {
  $r = Invoke-WebRequest -Uri "http://localhost:3214/health" -UseBasicParsing -TimeoutSec 5
  if ($r.StatusCode -eq 200) {
    Write-Host "Health check OK: $($r.Content)" -ForegroundColor Green
  } else {
    Write-Host "Health returned $($r.StatusCode): $($r.Content)" -ForegroundColor Yellow
  }
} catch {
  Write-Host "Could not reach /health: $_" -ForegroundColor Yellow
}
