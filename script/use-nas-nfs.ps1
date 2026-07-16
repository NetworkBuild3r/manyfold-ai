# Use Synology NFS for the organized 3D-Prints library, recreate Manyfold, full scan.
# Prerequisite: NFS rule on /volume1/Backups allows Docker (see script/NAS-NFS.md)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

$NfsDevice = if ($env:NFS_DEVICE) { $env:NFS_DEVICE } else { ":/volume1/Backups/3D-Prints" }
$NfsAddr = if ($env:NFS_ADDR) { $env:NFS_ADDR } else { "192.168.11.102" }
$VolName = "manyfold_prints_nfs"

Write-Host "==> Testing NFS mount from Docker (addr=$NfsAddr device=$NfsDevice)"
docker volume rm $VolName 2>$null | Out-Null
docker volume create `
  --driver local `
  --opt type=nfs `
  --opt "o=addr=$NfsAddr,rw,nolock,soft,nfsvers=3" `
  --opt "device=$NfsDevice" `
  $VolName | Out-Null

$listing = docker run --rm -v "${VolName}:/data:ro" alpine ls /data 2>&1
if ($LASTEXITCODE -ne 0 -or ($listing -join "`n") -notmatch "Anime") {
  Write-Host "NFS mount failed or empty. Output:"
  Write-Host $listing
  Write-Host ""
  Write-Host "Fix Synology NFS permissions first — see script/NAS-NFS.md"
  docker volume rm $VolName 2>$null | Out-Null
  exit 1
}

Write-Host "NFS OK:"
$listing | Select-Object -First 20

# Point compose at the named volume via a thin wrapper compose file
$override = @"
services:
  web:
    volumes:
      - manyfold_config:/config
      - $VolName:/libraries/prints
      - ./bin/docker-entrypoint.sh:/usr/src/app/bin/docker-entrypoint.sh:ro
      - ./app/jobs/scan:/usr/src/app/app/jobs/scan:ro
  worker:
    volumes:
      - manyfold_config:/config
      - $VolName:/libraries/prints
      - ./bin/docker-entrypoint.sh:/usr/src/app/bin/docker-entrypoint.sh:ro
      - ./app/jobs/scan:/usr/src/app/app/jobs/scan:ro
  worker_perf:
    volumes:
      - manyfold_config:/config
      - $VolName:/libraries/prints
      - ./bin/docker-entrypoint.sh:/usr/src/app/bin/docker-entrypoint.sh:ro
      - ./app/jobs/scan:/usr/src/app/app/jobs/scan:ro

volumes:
  $VolName:
    external: true
"@
$overridePath = "docker-compose.nas-nfs.yml"
Set-Content -Path $overridePath -Value $override -Encoding UTF8

@"
SKIP_LIBRARY_CHOWN=1
# LIBRARY_MOUNT unused when nas-nfs override is active
"@ | Set-Content .env -Encoding UTF8

Write-Host "==> Recreating stack with NFS library"
docker compose -f docker-compose.yml -f $overridePath up -d --force-recreate web worker worker_perf

Write-Host "==> Waiting for Sidekiq"
$ok = $false
for ($i = 1; $i -le 40; $i++) {
  $ps = docker compose exec -T worker ps aux 2>$null
  if ($ps -match "sidekiq") { $ok = $true; break }
  Start-Sleep 2
}
if (-not $ok) { Write-Host "WARN: Sidekiq not seen yet" } else { Write-Host "Sidekiq up" }

Write-Host "==> Library check"
docker compose -f docker-compose.yml -f $overridePath exec -T web sh -c "ls /libraries/prints | head -20"

Write-Host "==> Enqueue full scan"
docker cp script/enqueue_full_scan.rb manyfold-ai-web-1:/tmp/enqueue_full_scan.rb
docker compose -f docker-compose.yml -f $overridePath exec -T web bundle exec rails runner /tmp/enqueue_full_scan.rb

Write-Host "Done. Watch model count:"
Write-Host '  docker compose exec web bundle exec rails runner "puts Model.count"'
