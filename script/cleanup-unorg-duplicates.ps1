<#
.SYNOPSIS
  Find and remove duplicate dumps in 3D-Prints-Unorg (and similar folders).

.DESCRIPTION
  Targets the patterns that pile up from Drive / Explorer / re-downloads:

  1. Names starting with "Copy of "
  2. Windows/Drive style "name (1).zip", "name (2)" folders
  3. Exact same leaf name + same size in the same directory (keep oldest)
  4. Optional: same size + same SHA256 under a directory (keep oldest path)

  Default is DRY-RUN. Pass -Apply to delete. Deletes go to the recycle bin when
  possible on local drives; on network UNC/NAS paths files are permanently removed
  (Windows recycle bin does not cover network shares).

.EXAMPLE
  # Dry-run whole Unorg
  .\script\cleanup-unorg-duplicates.ps1

.EXAMPLE
  # Only etsy bucket, apply
  .\script\cleanup-unorg-duplicates.ps1 -Path 'W:\3D-Prints-Unorg\etsy' -Apply

.EXAMPLE
  # Name-pattern dups only (fast)
  .\script\cleanup-unorg-duplicates.ps1 -NamePatternsOnly -Apply

.EXAMPLE
  # Drop an entire folder after reviewing
  .\script\cleanup-unorg-duplicates.ps1 -DropPath 'W:\3D-Prints-Unorg\etsy' -Apply
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
  [string]$Root = 'W:\3D-Prints-Unorg',
  # Scan only this path (file/folder). Overrides -Root for discovery.
  [string]$Path = '',
  # Completely remove this folder/file (use for junk buckets like a bad etsy dump)
  [string]$DropPath = '',
  [switch]$Apply,
  [switch]$NamePatternsOnly,
  [switch]$ContentHash,
  [int]$MaxDepth = 10,
  [string]$LogDir = ''
)

$ErrorActionPreference = 'Continue'

function Write-Info([string]$m) { Write-Host $m }
function Write-Warn2([string]$m) { Write-Host "WARN: $m" -ForegroundColor Yellow }

function Get-SafeName([string]$n) {
  return $n.Trim()
}

function Test-IsCopyName {
  param([string]$Name)
  if ($Name -like 'Copy of *') { return $true }
  if ($Name -like 'Copy of *' ) { return $true }
  # "foo (1).zip" / "foo (2)" / "foo - Copy.zip"
  if ($Name -match ' \(\d+\)(\.[^.]*)?$') { return $true }
  if ($Name -match ' - Copy(\.[^.]*)?$') { return $true }
  if ($Name -match '^Copy \d+ of ') { return $true }
  return $false
}

function Get-OriginalNameGuess {
  param([string]$Name)
  $n = $Name
  if ($n -like 'Copy of *') {
    $n = $n.Substring(8).Trim()
  }
  $n = $n -replace ' \(\d+\)(\.[^.]+)?$', '$1'
  $n = $n -replace ' - Copy(\.[^.]+)?$', '$1'
  $n = $n -replace '^Copy \d+ of ', ''
  return $n.Trim()
}

function Remove-ItemSafe {
  param(
    [string]$Target,
    [string]$Reason
  )
  if (-not (Test-Path -LiteralPath $Target)) { return $false }
  if (-not $Apply) {
    Write-Info "WOULD DELETE [$Reason]: $Target"
    return $true
  }
  try {
    # Network paths: -RecycleBin not available; permanent delete
    Remove-Item -LiteralPath $Target -Recurse -Force -ErrorAction Stop
    Write-Info "DELETED [$Reason]: $Target"
    return $true
  } catch {
    Write-Warn2 "Failed to delete $Target - $($_.Exception.Message)"
    return $false
  }
}

function Get-FileLengthSafe {
  param($Item)
  try {
    if ($Item.PSIsContainer) { return 0 }
    return [long]$Item.Length
  } catch { return 0 }
}

function Walk-Collect {
  param([string]$Start, [int]$DepthLimit)

  $files = New-Object System.Collections.Generic.List[object]
  $dirs = New-Object System.Collections.Generic.List[object]
  $q = [System.Collections.Generic.Queue[object]]::new()
  $q.Enqueue([pscustomobject]@{ Path = $Start; Depth = 0 })

  while ($q.Count -gt 0) {
    $cur = $q.Dequeue()
    if ($cur.Depth -gt $DepthLimit) { continue }
    $leaf = Split-Path $cur.Path -Leaf
    if ($leaf -like '.*' -and $cur.Depth -gt 0) { continue }
    if ($leaf -in @('#recycle', '@eaDir', '.inventory', '.manyfold-organize-logs')) { continue }

    try {
      Get-ChildItem -LiteralPath $cur.Path -File -ErrorAction SilentlyContinue | ForEach-Object {
        $files.Add($_) | Out-Null
      }
      if ($cur.Depth -lt $DepthLimit) {
        Get-ChildItem -LiteralPath $cur.Path -Directory -ErrorAction SilentlyContinue |
          Where-Object { $_.Name -notlike '.*' -and $_.Name -notin @('#recycle', '@eaDir') } |
          ForEach-Object {
            $dirs.Add($_) | Out-Null
            $q.Enqueue([pscustomobject]@{ Path = $_.FullName; Depth = $cur.Depth + 1 })
          }
      }
    } catch {
      Write-Warn2 "scan: $($cur.Path) - $($_.Exception.Message)"
    }
  }
  return [pscustomobject]@{ Files = $files; Dirs = $dirs }
}

# --- main ---
$mode = if ($Apply) { 'APPLY' } else { 'DRY-RUN (pass -Apply to delete)' }
Write-Info "=== cleanup-unorg-duplicates ($mode) ==="

if (-not $LogDir) {
  $LogDir = Join-Path $Root '.manyfold-organize-logs'
}
if (-not (Test-Path -LiteralPath $LogDir)) {
  try { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null } catch {}
}

$report = New-Object System.Collections.Generic.List[object]
$bytesFreed = [long]0
$deleted = 0

# 1) Optional full drop of a path
if ($DropPath) {
  Write-Info "Drop target: $DropPath"
  if (-not (Test-Path -LiteralPath $DropPath)) {
    Write-Warn2 "DropPath not found: $DropPath"
  } else {
    $item = Get-Item -LiteralPath $DropPath
    $sizeNote = ''
    if (-not $item.PSIsContainer) {
      $sizeNote = " ($([math]::Round($item.Length/1MB,1)) MB)"
      $bytesFreed += $item.Length
    }
    if (Remove-ItemSafe -Target $DropPath -Reason "drop-path$sizeNote") {
      $deleted++
      $report.Add([pscustomobject]@{
          Action = if ($Apply) { 'deleted' } else { 'would-delete' }
          Reason = 'drop-path'
          Path   = $DropPath
        }) | Out-Null
    }
  }
  if (-not $Path -and -not $Root) {
    # only drop requested
  }
}

# 2) Duplicate scan
$scanRoot = if ($Path) { $Path } else { $Root }
if ($scanRoot -and (Test-Path -LiteralPath $scanRoot) -and -not ($DropPath -and -not $Path -and $DropPath -eq $scanRoot -and $Apply)) {
  # If we just deleted DropPath and it was the only target, skip scan of missing path
  if ($Apply -and $DropPath -and $DropPath -eq $scanRoot -and -not (Test-Path -LiteralPath $scanRoot)) {
    Write-Info "Scan root was dropped; skipping duplicate walk."
  } else {
    Write-Info "Scanning: $scanRoot (max depth $MaxDepth)"
    $collected = Walk-Collect -Start $scanRoot -DepthLimit $MaxDepth
    Write-Info "Found $($collected.Files.Count) files, $($collected.Dirs.Count) dirs"

    # --- name-pattern duplicates (Copy of / (1)) ---
    $patternItems = @()
    foreach ($f in $collected.Files) {
      if (Test-IsCopyName $f.Name) { $patternItems += $f }
    }
    foreach ($d in $collected.Dirs) {
      if (Test-IsCopyName $d.Name) { $patternItems += $d }
    }
    Write-Info "Name-pattern copies: $($patternItems.Count)"

    foreach ($item in $patternItems) {
      $len = Get-FileLengthSafe $item
      if (Remove-ItemSafe -Target $item.FullName -Reason "copy-name ($([math]::Round($len/1MB,1))MB)") {
        $deleted++
        $bytesFreed += $len
        $report.Add([pscustomobject]@{
            Action = if ($Apply) { 'deleted' } else { 'would-delete' }
            Reason = 'copy-name'
            Path   = $item.FullName
            Bytes  = $len
            OriginalGuess = (Get-OriginalNameGuess $item.Name)
          }) | Out-Null
      }
    }

    if (-not $NamePatternsOnly) {
      # --- same directory: same leaf name + same size (keep oldest LastWriteTime) ---
      # Re-scan files after pattern deletes? Use original list filtered by still-exists for dry-run accuracy
      $byDirName = @{}
      foreach ($f in $collected.Files) {
        if ($Apply -and -not (Test-Path -LiteralPath $f.FullName)) { continue }
        if (Test-IsCopyName $f.Name) { continue } # already handled
        $dir = $f.DirectoryName
        $key = ($dir + '|' + $f.Name.ToLowerInvariant() + '|' + $f.Length).ToLowerInvariant()
        # Actually same name in same dir can't happen twice on case-insensitive FS
        # Instead: group by dir + size + normalized name without (1)/Copy of
        $norm = (Get-OriginalNameGuess $f.Name).ToLowerInvariant()
        $gkey = ($dir + '||' + $norm + '||' + $f.Length)
        if (-not $byDirName.ContainsKey($gkey)) {
          $byDirName[$gkey] = New-Object System.Collections.Generic.List[object]
        }
        $byDirName[$gkey].Add($f) | Out-Null
      }

      $sameNameSizeGroups = @($byDirName.GetEnumerator() | Where-Object { $_.Value.Count -gt 1 })
      Write-Info "Same-folder normalized-name+size groups: $($sameNameSizeGroups.Count)"

      foreach ($g in $sameNameSizeGroups) {
        $ordered = @($g.Value | Sort-Object LastWriteTime, FullName)
        $keep = $ordered[0]
        foreach ($dup in $ordered | Select-Object -Skip 1) {
          $len = Get-FileLengthSafe $dup
          if (Remove-ItemSafe -Target $dup.FullName -Reason "same-name-size keep=$($keep.Name)") {
            $deleted++
            $bytesFreed += $len
            $report.Add([pscustomobject]@{
                Action = if ($Apply) { 'deleted' } else { 'would-delete' }
                Reason = 'same-name-size'
                Path   = $dup.FullName
                Keep   = $keep.FullName
                Bytes  = $len
              }) | Out-Null
          }
        }
      }

      if ($ContentHash) {
        Write-Info "Content-hash pass (same size groups >= 2)..."
        $bySize = @{}
        foreach ($f in $collected.Files) {
          if ($Apply -and -not (Test-Path -LiteralPath $f.FullName)) { continue }
          if ($f.Length -lt 1KB) { continue }
          $k = [string]$f.Length
          if (-not $bySize.ContainsKey($k)) { $bySize[$k] = New-Object System.Collections.Generic.List[object] }
          $bySize[$k].Add($f) | Out-Null
        }
        $hashGroups = 0
        foreach ($sg in $bySize.GetEnumerator()) {
          if ($sg.Value.Count -lt 2) { continue }
          $hashes = @{}
          foreach ($f in $sg.Value) {
            if ($Apply -and -not (Test-Path -LiteralPath $f.FullName)) { continue }
            try {
              $h = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
            } catch { continue }
            if (-not $hashes.ContainsKey($h)) {
              $hashes[$h] = New-Object System.Collections.Generic.List[object]
            }
            $hashes[$h].Add($f) | Out-Null
          }
          foreach ($hg in $hashes.GetEnumerator()) {
            if ($hg.Value.Count -lt 2) { continue }
            $hashGroups++
            $ordered = @($hg.Value | Sort-Object LastWriteTime, FullName)
            $keep = $ordered[0]
            foreach ($dup in $ordered | Select-Object -Skip 1) {
              $len = Get-FileLengthSafe $dup
              if (Remove-ItemSafe -Target $dup.FullName -Reason "sha256-dup keep=$($keep.FullName)") {
                $deleted++
                $bytesFreed += $len
                $report.Add([pscustomobject]@{
                    Action = if ($Apply) { 'deleted' } else { 'would-delete' }
                    Reason = 'sha256'
                    Path   = $dup.FullName
                    Keep   = $keep.FullName
                    Bytes  = $len
                  }) | Out-Null
              }
            }
          }
        }
        Write-Info "SHA256 duplicate groups: $hashGroups"
      }
    }
  }
}

Write-Info ""
Write-Info "=== Summary ==="
Write-Info "Actions: $deleted"
Write-Info "Bytes:   $([math]::Round($bytesFreed/1GB, 2)) GB (approx; dirs count as 0)"
if (-not $Apply) { Write-Info "Dry-run only. Re-run with -Apply to delete." }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$logPath = Join-Path $LogDir "cleanup-duplicates-$stamp.json"
try {
  $report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $logPath -Encoding UTF8
  Write-Info "Log: $logPath"
} catch {
  Write-Warn2 "Log write failed: $($_.Exception.Message)"
}

Write-Info ""
Write-Info "Sample (up to 20):"
$report | Select-Object -First 20 | ForEach-Object {
  Write-Info ("  [{0}] {1}" -f $_.Reason, $_.Path)
}
