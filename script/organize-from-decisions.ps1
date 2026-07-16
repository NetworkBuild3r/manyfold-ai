<#
.SYNOPSIS
  Apply inventory gallery decisions: move Unorg items into Manyfold 3D-Prints categories.

.DESCRIPTION
  Reads decisions.json exported from inventory-catalog gallery
  (items marked Move with a category).

  Manyfold layout:
    3D-Prints\<Category>\<Model Name>\

.EXAMPLE
  # Dry-run
  .\script\organize-from-decisions.ps1 -DecisionsPath .\decisions.json

  # Apply
  .\script\organize-from-decisions.ps1 -DecisionsPath .\decisions.json -Apply
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$DecisionsPath,
  [string]$DestRoot = '\\192.168.11.102\Backups\3D-Prints',
  [switch]$Apply,
  [string]$LogDir = '\\192.168.11.102\Backups\3D-Prints-Unorg\.manyfold-organize-logs'
)

$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$logFile = Join-Path $LogDir ("from-decisions-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))

function Write-Log([string]$msg) {
  $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
  Write-Host $line
  Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
}

function Get-SafeName {
  param([string]$Name)
  if ([string]::IsNullOrWhiteSpace($Name)) { return 'unnamed-model' }
  $n = $Name.Trim()
  $n = $n -replace '^(Copy of|copy of)\s+', ''
  $n = $n -replace '[<>:"/\\|?*\x00-\x1F]', ' '
  $n = $n -replace '\s+', ' '
  $n = $n.Trim(' .')
  if ($n.Length -gt 120) { $n = $n.Substring(0, 120).Trim() }
  if ([string]::IsNullOrWhiteSpace($n)) { $n = 'unnamed-model' }
  return $n
}

function Get-UniqueDest([string]$Category, [string]$ModelName) {
  $destDir = Join-Path $DestRoot $Category
  $candidate = Join-Path $destDir $ModelName
  if (-not (Test-Path -LiteralPath $candidate)) { return $candidate }
  $i = 2
  while ($true) {
    $alt = Join-Path $destDir ("$ModelName ($i)")
    if (-not (Test-Path -LiteralPath $alt)) { return $alt }
    $i++
  }
}

if (-not (Test-Path -LiteralPath $DecisionsPath)) {
  throw "Decisions file not found: $DecisionsPath"
}
if (-not (Test-Path -LiteralPath $DestRoot)) {
  throw "Dest root not found: $DestRoot"
}

$raw = Get-Content -LiteralPath $DecisionsPath -Raw -Encoding UTF8 | ConvertFrom-Json
$decisions = @($raw.decisions)
if ($decisions.Count -eq 0) {
  Write-Log "No decisions to apply."
  return
}

Write-Log "Mode: $(if ($Apply) { 'APPLY' } else { 'DRY-RUN' })"
Write-Log "Decisions: $($decisions.Count)"
Write-Log "Dest: $DestRoot"

$moved = 0
$skipped = 0
foreach ($d in $decisions) {
  $src = $d.sourcePath
  $cat = $d.category
  $name = Get-SafeName $d.name
  $kind = $d.kind

  if (-not $src -or -not (Test-Path -LiteralPath $src)) {
    Write-Log "SKIP missing: $src"
    $skipped++
    continue
  }
  if (-not $cat) {
    Write-Log "SKIP no category: $src"
    $skipped++
    continue
  }

  $dest = Get-UniqueDest -Category $cat -ModelName $name
  $destName = Split-Path $dest -Leaf
  Write-Log "$(if ($Apply) { 'MOVE' } else { 'DRY' }) $src  ->  $cat\$destName  ($kind)"

  if (-not $Apply) { $moved++; continue }

  $catPath = Join-Path $DestRoot $cat
  if (-not (Test-Path -LiteralPath $catPath)) {
    New-Item -ItemType Directory -Path $catPath -Force | Out-Null
  }

  if ($kind -eq 'archive') {
    New-Item -ItemType Directory -Path $dest -Force | Out-Null
    Move-Item -LiteralPath $src -Destination (Join-Path $dest (Split-Path $src -Leaf))
  } else {
    # Rename in place if needed, then move folder
    $parent = Split-Path $src -Parent
    $currentName = Split-Path $src -Leaf
    $working = $src
    if ($currentName -ne $destName) {
      $tmpName = $destName
      $renamed = Join-Path $parent $tmpName
      if (Test-Path -LiteralPath $renamed) {
        $tmpName = "__mf_{0}_{1}" -f $destName, ([guid]::NewGuid().ToString('N').Substring(0, 6))
        $renamed = Join-Path $parent $tmpName
      }
      Rename-Item -LiteralPath $src -NewName $tmpName
      $working = $renamed
    }
    Move-Item -LiteralPath $working -Destination $dest
  }
  $moved++
}

Write-Log "Done. planned/moved=$moved skipped=$skipped"
Write-Log "Log: $logFile"
if (-not $Apply) {
  Write-Host ""
  Write-Host "Dry-run only. Re-run with -Apply to move files." -ForegroundColor Cyan
}
