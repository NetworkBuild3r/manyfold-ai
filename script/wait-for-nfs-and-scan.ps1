# Polls until Synology NFS allows Docker, then mounts library and runs full scan.
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot\..

$NfsDevice = ":/volume1/Backups/3D-Prints"
$NfsAddr = "192.168.11.102"
$VolName = "manyfold_prints_nfs"
$MaxTries = 60
$SleepSec = 15

Write-Host ""
Write-Host "============================================================"
Write-Host "  Waiting for Synology NFS to allow Docker Desktop"
Write-Host "============================================================"
Write-Host "  On the NAS (DSM):"
Write-Host "  1. Control Panel -> Shared Folder -> Backups -> NFS"
Write-Host "  2. Edit/add client rule for /volume1/Backups:"
Write-Host "       Hostname/IP:  *   (or 172.16.0.0/12 and 192.168.65.0/24)"
Write-Host "       Privilege:    Read/Write"
Write-Host "       Enable: Allow connections from non-privileged ports"
Write-Host "  3. Save / Apply"
Write-Host "  This script polls every $SleepSec seconds then full-scans."
Write-Host "============================================================"
Write-Host ""

function Test-Nfs {
  docker volume rm $VolName 2>$null | Out-Null
  docker volume create --driver local --opt type=nfs --opt "o=addr=$NfsAddr,rw,nolock,soft,nfsvers=3" --opt "device=$NfsDevice" $VolName 2>$null | Out-Null
  $out = docker run --rm -v "${VolName}:/data:ro" alpine ls /data 2>&1 | Out-String
  if ($LASTEXITCODE -eq 0 -and $out -match "Anime") {
    return $true
  }
  docker volume rm $VolName 2>$null | Out-Null
  return $false
}

$ok = $false
for ($i = 1; $i -le $MaxTries; $i++) {
  Write-Host "[$i/$MaxTries] Testing NFS from Docker..."
  if (Test-Nfs) {
    $ok = $true
    Write-Host "NFS is available!"
    break
  }
  Write-Host "  still permission denied / empty - fix NFS on DSM, then wait..."
  Start-Sleep -Seconds $SleepSec
}

if (-not $ok) {
  Write-Host "Timed out waiting for NFS. Re-run after fixing DSM permissions."
  exit 1
}

& "$PSScriptRoot\use-nas-nfs.ps1"
exit $LASTEXITCODE
