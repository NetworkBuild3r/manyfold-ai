<#
.SYNOPSIS
  Extract all .zip / .rar / .7z archives under a folder into per-archive model folders.

.DESCRIPTION
  For each archive (e.g. "Abe3D - Elektra.rar"):
    Creates:  <parent>\Abe3D - Elektra\
    Extracts: archive contents into that folder (via 7-Zip)

  Defaults to W:\3D-Prints-Unorg\etsy. Dry-run unless -Apply.

.EXAMPLE
  # Dry-run etsy
  .\script\extract-all-archives.ps1

.EXAMPLE
  # Extract everything in etsy
  .\script\extract-all-archives.ps1 -Apply

.EXAMPLE
  # Another folder, delete archives after successful extract
  .\script\extract-all-archives.ps1 -Path 'W:\3D-Prints-Unorg\AnySTL' -Apply -DeleteArchive
#>
[CmdletBinding()]
param(
  [string]$Path = 'W:\3D-Prints-Unorg\etsy',
  [switch]$Apply,
  [switch]$DeleteArchive,
  # Skip if destination folder already has any files
  [switch]$Force,
  [int]$MaxDepth = 4,
  [string]$SevenZip = '',
  [string]$LogDir = ''
)

$ErrorActionPreference = 'Continue'

function Write-Info([string]$m) { Write-Host $m }
function Write-Warn2([string]$m) { Write-Host "WARN: $m" -ForegroundColor Yellow }

function Find-SevenZip {
  if ($SevenZip -and (Test-Path -LiteralPath $SevenZip)) { return $SevenZip }
  $candidates = @(
    'C:\Program Files\7-Zip\7z.exe',
    'C:\Program Files (x86)\7-Zip\7z.exe',
    (Join-Path $env:LOCALAPPDATA 'Programs\7-Zip\7z.exe')
  )
  foreach ($c in $candidates) {
    if (Test-Path -LiteralPath $c) { return $c }
  }
  $cmd = Get-Command 7z.exe -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  return $null
}

function Get-SafeFolderName([string]$name) {
  $n = $name.Trim().TrimEnd('.')
  $n = $n -replace '[<>:"/\\|?*\x00-\x1F]', ' '
  $n = $n -replace '\s+', ' '
  $n = $n.Trim()
  if ([string]::IsNullOrWhiteSpace($n)) { $n = 'unnamed-model' }
  if ($n.Length -gt 120) { $n = $n.Substring(0, 120).Trim() }
  return $n
}

function Get-Archives {
  param([string]$Root, [int]$Depth)
  $exts = @('.zip', '.rar', '.7z', '.cbz')
  $list = New-Object System.Collections.Generic.List[System.IO.FileInfo]
  $q = [System.Collections.Generic.Queue[object]]::new()
  $q.Enqueue([pscustomobject]@{ P = $Root; D = 0 })
  while ($q.Count -gt 0) {
    $c = $q.Dequeue()
    if ($c.D -gt $Depth) { continue }
    $leaf = Split-Path $c.P -Leaf
    if ($leaf -like '.*' -and $c.D -gt 0) { continue }
    if ($leaf -in @('#recycle', '@eaDir', '_from_drive', 'images')) { continue }
    try {
      Get-ChildItem -LiteralPath $c.P -File -ErrorAction SilentlyContinue |
        Where-Object { $exts -contains $_.Extension.ToLowerInvariant() } |
        ForEach-Object { $list.Add($_) | Out-Null }
      if ($c.D -lt $Depth) {
        Get-ChildItem -LiteralPath $c.P -Directory -ErrorAction SilentlyContinue |
          Where-Object {
            $_.Name -notlike '.*' -and
            $_.Name -notin @('#recycle', '@eaDir', '_from_drive')
          } |
          ForEach-Object { $q.Enqueue([pscustomobject]@{ P = $_.FullName; D = $c.D + 1 }) }
      }
    } catch {}
  }
  return $list
}

function Test-FolderHasContent([string]$dir) {
  if (-not (Test-Path -LiteralPath $dir)) { return $false }
  $any = Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notin @('.', '..') } |
    Select-Object -First 1
  return $null -ne $any
}

function Expand-Archive7z {
  param(
    [string]$SevenZipExe,
    [string]$ArchivePath,
    [string]$DestDir
  )
  if (-not (Test-Path -LiteralPath $DestDir)) {
    New-Item -ItemType Directory -Path $DestDir -Force | Out-Null
  }
  # x = extract with full paths; -y = yes; -o = output (no space after -o)
  $args = @('x', '-y', "-o$DestDir", '--', $ArchivePath)
  $p = Start-Process -FilePath $SevenZipExe -ArgumentList $args -Wait -PassThru -NoNewWindow
  return $p.ExitCode
}

# --- main ---
if (-not (Test-Path -LiteralPath $Path)) { throw "Path not found: $Path" }

$sz = Find-SevenZip
if (-not $sz) {
  throw "7-Zip not found. Install from https://www.7-zip.org/ (needed for .rar as well as .zip)."
}

$mode = if ($Apply) { 'APPLY' } else { 'DRY-RUN (pass -Apply to extract)' }
Write-Info "=== extract-all-archives ($mode) ==="
Write-Info "Path:    $Path"
Write-Info "7-Zip:   $sz"
Write-Info "Delete archives after extract: $DeleteArchive"

$archives = @(Get-Archives -Root $Path -Depth $MaxDepth | Sort-Object FullName)
Write-Info "Archives found: $($archives.Count)"

if (-not $LogDir) {
  $parent = Split-Path $Path -Parent
  $LogDir = Join-Path $parent '.manyfold-organize-logs'
}
if (-not (Test-Path -LiteralPath $LogDir)) {
  try { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null } catch {}
}

$report = New-Object System.Collections.Generic.List[object]
$ok = 0
$skip = 0
$fail = 0
$i = 0

foreach ($arc in $archives) {
  $i++
  $base = Get-SafeFolderName ([IO.Path]::GetFileNameWithoutExtension($arc.Name))
  $dest = Join-Path $arc.DirectoryName $base

  # Don't extract into a folder that would nest oddly if archive already inside its own folder
  if ($arc.Directory.Name -eq $base) {
    $dest = $arc.DirectoryName
  }

  $hasContent = Test-FolderHasContent $dest
  if ($hasContent -and -not $Force) {
    if (($i % 50) -eq 0 -or $i -eq 1) {
      Write-Info "[$i/$($archives.Count)] SKIP (exists): $($arc.Name)"
    }
    $report.Add([pscustomobject]@{
        Action = 'skip-exists'
        Archive = $arc.FullName
        Dest    = $dest
        Bytes   = $arc.Length
      }) | Out-Null
    $skip++
    continue
  }

  Write-Info "[$i/$($archives.Count)] $($arc.Name) ($([math]::Round($arc.Length/1MB,1)) MB) -> $base\"

  if (-not $Apply) {
    $report.Add([pscustomobject]@{
        Action  = 'would-extract'
        Archive = $arc.FullName
        Dest    = $dest
        Bytes   = $arc.Length
      }) | Out-Null
    $ok++
    continue
  }

  try {
    $code = Expand-Archive7z -SevenZipExe $sz -ArchivePath $arc.FullName -DestDir $dest
    if ($code -ne 0 -and $code -ne 1) {
      # 7z: 0=ok, 1=warning (e.g. non-fatal)
      Write-Warn2 "7z exit $code for $($arc.Name)"
      $report.Add([pscustomobject]@{
          Action  = 'fail'
          Archive = $arc.FullName
          Dest    = $dest
          ExitCode = $code
        }) | Out-Null
      $fail++
      continue
    }

    $report.Add([pscustomobject]@{
        Action  = 'extracted'
        Archive = $arc.FullName
        Dest    = $dest
        Bytes   = $arc.Length
        ExitCode = $code
      }) | Out-Null
    $ok++

    if ($DeleteArchive) {
      try {
        Remove-Item -LiteralPath $arc.FullName -Force
        Write-Info "  deleted archive"
      } catch {
        Write-Warn2 "  could not delete archive: $($_.Exception.Message)"
      }
    }
  } catch {
    Write-Warn2 "Failed $($arc.FullName): $($_.Exception.Message)"
    $report.Add([pscustomobject]@{
        Action  = 'error'
        Archive = $arc.FullName
        Error   = $_.Exception.Message
      }) | Out-Null
    $fail++
  }
}

Write-Info ""
Write-Info "=== Summary ==="
Write-Info "Extracted / would extract: $ok"
Write-Info "Skipped (already had content): $skip"
Write-Info "Failed: $fail"
if (-not $Apply) { Write-Info "Dry-run only. Re-run with -Apply to extract." }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$log = Join-Path $LogDir "extract-all-archives-$stamp.json"
try {
  $report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $log -Encoding UTF8
  Write-Info "Log: $log"
} catch {
  Write-Warn2 "Log write failed: $($_.Exception.Message)"
}
