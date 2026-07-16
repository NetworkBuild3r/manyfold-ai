<#
.SYNOPSIS
  1) Rename "Copy of Foo.ext" -> "Foo.ext"
  2) Delete "Foo (1).ext", "Foo (2).ext", etc. when a clean "Foo.ext" exists
     (or promote the lowest (n) to clean name if no clean file exists, then delete other (n)s)

.EXAMPLE
  .\script\dedupe-copy-of-names.ps1 -Path 'W:\3D-Prints-Unorg\etsy' -Apply
#>
[CmdletBinding()]
param(
  [string]$Path = 'W:\3D-Prints-Unorg\etsy',
  [switch]$Apply,
  [int]$MaxDepth = 6
)

$ErrorActionPreference = 'Continue'
$report = New-Object System.Collections.Generic.List[object]

function Write-Info($m) { Write-Host $m }

function Get-Files {
  param([string]$Root, [int]$Depth)
  $list = New-Object System.Collections.Generic.List[System.IO.FileInfo]
  $q = [System.Collections.Generic.Queue[object]]::new()
  $q.Enqueue([pscustomobject]@{ P = $Root; D = 0 })
  while ($q.Count -gt 0) {
    $c = $q.Dequeue()
    if ($c.D -gt $Depth) { continue }
    $leaf = Split-Path $c.P -Leaf
    if ($leaf -like '.*' -and $c.D -gt 0) { continue }
    try {
      Get-ChildItem -LiteralPath $c.P -File -ErrorAction SilentlyContinue | ForEach-Object { $list.Add($_) | Out-Null }
      if ($c.D -lt $Depth) {
        Get-ChildItem -LiteralPath $c.P -Directory -ErrorAction SilentlyContinue |
          Where-Object { $_.Name -notlike '.*' -and $_.Name -notin @('#recycle', '@eaDir') } |
          ForEach-Object { $q.Enqueue([pscustomobject]@{ P = $_.FullName; D = $c.D + 1 }) }
      }
    } catch {}
  }
  return $list
}

function Strip-CopyOfPrefix([string]$name) {
  $n = $name
  # "Copy of ", "Copy of - ", repeated
  while ($n -match '^(?i)Copy of\s*') {
    $n = $n -replace '^(?i)Copy of\s*', ''
  }
  # leftover " - Name" or "- Name" from "Copy of - Name"
  $n = $n -replace '^\s*-\s+', ''
  return $n.Trim()
}

function Test-HasNumberSuffix([string]$name) {
  # "Foo (1).rar" or "Foo (2)"
  return $name -match ' \(\d+\)(\.[^.]*)?$'
}

function Get-BaseWithoutNumber([string]$name) {
  # "Foo (1).rar" -> "Foo.rar" ; "Foo (2)" -> "Foo"
  if ($name -match '^(.*) \(\d+\)(\.[^.]+)$') {
    return $Matches[1] + $Matches[2]
  }
  if ($name -match '^(.*) \(\d+)$') {
    return $Matches[1]
  }
  return $name
}

function Get-NumberSuffix([string]$name) {
  if ($name -match ' \((\d+)\)(\.[^.]*)?$') { return [int]$Matches[1] }
  return $null
}

if (-not (Test-Path -LiteralPath $Path)) { throw "Path not found: $Path" }

$mode = if ($Apply) { 'APPLY' } else { 'DRY-RUN' }
Write-Info "=== dedupe-copy-of-names ($mode) ==="
Write-Info "Path: $Path"

$files = @(Get-Files -Root $Path -Depth $MaxDepth)
Write-Info "Files found: $($files.Count)"

# ---------- Pass 1: strip "Copy of " ----------
$renamed = 0
$renameSkip = 0
foreach ($f in @($files | Sort-Object FullName)) {
  if ($f.Name -notmatch '^(?i)Copy of\s') { continue }
  $newName = Strip-CopyOfPrefix $f.Name
  if ([string]::IsNullOrWhiteSpace($newName) -or $newName -eq $f.Name) { continue }

  $dest = Join-Path $f.DirectoryName $newName
  if (Test-Path -LiteralPath $dest) {
    $existing = Get-Item -LiteralPath $dest
    # Same size => pure dup of existing; delete the Copy of
    if (-not $existing.PSIsContainer -and $existing.Length -eq $f.Length) {
      if ($Apply) {
        Remove-Item -LiteralPath $f.FullName -Force
        Write-Info "DEL (dup of existing): $($f.Name)"
      } else {
        Write-Info "WOULD DEL (dup of existing): $($f.FullName)"
      }
      $report.Add([pscustomobject]@{ Action = 'delete-dup-after-rename-collision'; Path = $f.FullName; Keep = $dest }) | Out-Null
      $renamed++ # count as handled
      continue
    }
    Write-Info "SKIP rename collision (different/exists): $($f.Name) -> $newName"
    $renameSkip++
    $report.Add([pscustomobject]@{ Action = 'skip-collision'; Path = $f.FullName; Target = $dest }) | Out-Null
    continue
  }

  if ($Apply) {
    Rename-Item -LiteralPath $f.FullName -NewName $newName -Force
    Write-Info "RENAME: $($f.Name) -> $newName"
  } else {
    Write-Info "WOULD RENAME: $($f.Name) -> $newName"
  }
  $report.Add([pscustomobject]@{ Action = 'rename'; From = $f.FullName; To = $dest }) | Out-Null
  $renamed++
}

Write-Info "Pass1 rename/handled: $renamed  skip-collision: $renameSkip"

# ---------- Pass 2: delete (n) suffixes ----------
# Refresh file list
$files2 = @(Get-Files -Root $Path -Depth $MaxDepth)
$byDirBase = @{}

foreach ($f in $files2) {
  if (-not (Test-HasNumberSuffix $f.Name)) { continue }
  $base = Get-BaseWithoutNumber $f.Name
  $key = ($f.DirectoryName + '|' + $base.ToLowerInvariant())
  if (-not $byDirBase.ContainsKey($key)) {
    $byDirBase[$key] = [pscustomobject]@{
      Dir  = $f.DirectoryName
      Base = $base
      Numbered = New-Object System.Collections.Generic.List[object]
      Clean = $null
    }
  }
  $byDirBase[$key].Numbered.Add($f) | Out-Null
}

# Find clean base files
foreach ($f in $files2) {
  if (Test-HasNumberSuffix $f.Name) { continue }
  $key = ($f.DirectoryName + '|' + $f.Name.ToLowerInvariant())
  if ($byDirBase.ContainsKey($key)) {
    $byDirBase[$key].Clean = $f
  }
}

$deleted = 0
$promoted = 0
foreach ($g in $byDirBase.Values) {
  $cleanPath = Join-Path $g.Dir $g.Base
  $hasClean = $null -ne $g.Clean -or (Test-Path -LiteralPath $cleanPath)

  if ($hasClean) {
    # Delete all (n) variants
    foreach ($n in $g.Numbered) {
      if (-not (Test-Path -LiteralPath $n.FullName)) { continue }
      if ($Apply) {
        Remove-Item -LiteralPath $n.FullName -Force
        Write-Info "DEL (n-suffix, clean exists): $($n.Name)"
      } else {
        Write-Info "WOULD DEL (n-suffix, clean exists): $($n.FullName)"
      }
      $report.Add([pscustomobject]@{ Action = 'delete-numbered'; Path = $n.FullName; Keep = $cleanPath }) | Out-Null
      $deleted++
    }
  } else {
    # No clean file: promote lowest number to clean name, delete the rest
    $ordered = @($g.Numbered | Sort-Object { Get-NumberSuffix $_.Name }, Length, FullName)
    if ($ordered.Count -eq 0) { continue }
    $keep = $ordered[0]
    $dest = Join-Path $g.Dir $g.Base
    if ($Apply) {
      if (-not (Test-Path -LiteralPath $dest)) {
        Rename-Item -LiteralPath $keep.FullName -NewName $g.Base -Force
        Write-Info "PROMOTE: $($keep.Name) -> $($g.Base)"
        $promoted++
        $report.Add([pscustomobject]@{ Action = 'promote'; From = $keep.FullName; To = $dest }) | Out-Null
      }
    } else {
      Write-Info "WOULD PROMOTE: $($keep.Name) -> $($g.Base)"
      $promoted++
    }
    foreach ($n in $ordered | Select-Object -Skip 1) {
      if (-not (Test-Path -LiteralPath $n.FullName)) { continue }
      # skip if we already renamed keep and path changed
      if ($Apply -and $n.FullName -eq $keep.FullName) { continue }
      if ($Apply) {
        Remove-Item -LiteralPath $n.FullName -Force -ErrorAction SilentlyContinue
        Write-Info "DEL (n-suffix after promote): $($n.Name)"
      } else {
        Write-Info "WOULD DEL (n-suffix after promote): $($n.FullName)"
      }
      $report.Add([pscustomobject]@{ Action = 'delete-numbered-after-promote'; Path = $n.FullName }) | Out-Null
      $deleted++
    }
  }
}

Write-Info ""
Write-Info "=== Summary ==="
Write-Info "Renames/handled Copy-of: $renamed"
Write-Info "Promoted (n)->clean:     $promoted"
Write-Info "Deleted (n) dups:        $deleted"
if (-not $Apply) { Write-Info "Dry-run only. Re-run with -Apply to change disk." }

$logDir = Join-Path (Split-Path $Path -Parent) '.manyfold-organize-logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$log = Join-Path $logDir ("dedupe-copy-of-$(Get-Date -Format yyyyMMdd-HHmmss).json")
$report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $log -Encoding UTF8
Write-Info "Log: $log"
