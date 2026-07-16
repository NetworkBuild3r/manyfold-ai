<#
.SYNOPSIS
  Move models from 3D-Prints-Unorg into the Manyfold-friendly 3D-Prints library layout.

.DESCRIPTION
  Manyfold treats each first-level subfolder of a category as one model:
    3D-Prints\<Category>\<Model Name>\*.stl|*.3mf|archives|preview|datapackage.json

  Default mode is DRY-RUN (plan only). Pass -Apply to perform moves.

.EXAMPLE
  # Preview everything
  .\script\organize-unorg.ps1

  # Apply only clean named buckets
  .\script\organize-unorg.ps1 -Buckets 'Dragon Ball Z','Star Wars','Halo','DC' -Apply

  # Apply Gamebody renames
  .\script\organize-unorg.ps1 -Buckets Gamebody -Apply
#>
[CmdletBinding()]
param(
  [string]$SourceRoot = '\\192.168.11.102\Backups\3D-Prints-Unorg',
  [string]$DestRoot = '\\192.168.11.102\Backups\3D-Prints',
  [string[]]$Buckets = @(),
  [switch]$Apply,
  [switch]$SkipImagesOnly,
  [string]$LogDir = '\\192.168.11.102\Backups\3D-Prints-Unorg\.manyfold-organize-logs'
)

$ErrorActionPreference = 'Stop'
$archiveExt = @('.rar', '.zip', '.7z', '.cbz')
$modelExt = @('.stl', '.obj', '.3mf', '.ply', '.gltf', '.glb', '.step', '.stp', '.fbx', '.gcode', '.lys', '.lyt', '.chitubox', '.ctb', '.sl1s') + $archiveExt

# Map unorg top-level bucket -> destination category under 3D-Prints
$bucketMap = [ordered]@{
  'Alita Battle Angel'                         = 'Movie TV'
  'AnySTL'                                     = '_any_stl_expand'   # special: expand subfolders
  'Archive'                                    = 'Unknown'
  'Artisan Guild'                              = 'D&D'
  'Busts Files'                                = 'Unknown'
  'Chibi'                                      = 'Anime'
  'Cults3D'                                    = 'Cults3D'
  'D&D'                                        = 'D&D'
  'DC'                                         = 'DC'
  'Dragon Ball Z'                              = 'Anime'
  'etsy'                                       = 'Unknown'           # mostly loose archives
  'Flexi'                                      = 'Unknown'
  'Gamebody'                                   = 'Games'
  'Halo'                                       = 'Games'
  'Harry Patter Chess Set'                     = 'Movie TV'
  'Helmet Mask'                                = 'Cosplay'
  'LOTR - keep - all'                          = 'Movie TV'
  'MartianSTLDESIGN'                           = 'Unknown'
  'Marvel Files'                               = 'Games'
  'MINIATURE FILES'                            = 'D&D'
  'Mixed'                                      = 'Unknown'
  'MovieTv'                                    = 'Movie TV'
  'Pokemon'                                    = 'Anime'
  'RN Estudio'                                 = 'Unknown'
  'Sailor Moon'                                = 'Anime'
  'Silver Eyes Fredbear cosplay mask 3D model' = 'Cosplay'
  'Star Wars'                                  = 'Movie TV'
  'Thingiverse'                                = 'Unknown'
  'Tytan Troll'                                = 'D&D'
  'Viking'                                     = 'Unknown'
  'Weapons'                                    = 'Cosplay'
  '_Uncategorized'                             = 'Unknown'
}

# AnySTL subcategory prefixes -> category
$anyStlMap = @{
  'anime'                 = 'Anime'
  'articulated'           = 'Unknown'
  'ashtray'               = 'Unknown'
  'b3dserk'               = 'B3dserk'
  'building'              = 'Unknown'
  'cake'                  = 'Unknown'
  'cartoon'               = 'Cartoons'
  'cosplay'               = 'Cosplay'
  'dnd'                   = 'D&D'
  'd&d'                   = 'D&D'
  'dc'                    = 'DC'
  'game'                  = 'Games'
  'marvel'                = 'Games'
  'movie'                 = 'Movie TV'
  'tv'                    = 'Movie TV'
  'helmet'                = 'Cosplay'
  'weapon'                = 'Cosplay'
  'miniature'             = 'D&D'
  'bust'                  = 'Unknown'
  'flexi'                 = 'Unknown'
}

function Write-Log {
  param([string]$Message, [string]$Level = 'INFO')
  $line = '[{0}] [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
  Write-Host $line
  if ($script:logFile) {
    Add-Content -LiteralPath $script:logFile -Value $line -Encoding UTF8
  }
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

function Test-HasModelFiles {
  param([string]$Path)
  if (-not (Test-Path -LiteralPath $Path)) { return $false }
  # Shallow first (fast on NAS), then one-level deep
  $files = Get-ChildItem -LiteralPath $Path -File -ErrorAction SilentlyContinue
  foreach ($f in $files) {
    if ($modelExt -contains $f.Extension.ToLowerInvariant()) { return $true }
  }
  $dirs = Get-ChildItem -LiteralPath $Path -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notlike '.*' -and $_.Name -notlike 'ALL *' }
  foreach ($d in $dirs) {
    $inner = Get-ChildItem -LiteralPath $d.FullName -File -ErrorAction SilentlyContinue |
      Select-Object -First 30
    foreach ($f in $inner) {
      if ($modelExt -contains $f.Extension.ToLowerInvariant()) { return $true }
    }
  }
  return $false
}

function Get-ModelNameFromFolder {
  param([System.IO.DirectoryInfo]$Dir)

  $name = $Dir.Name

  # Opaque dump codes: GAMEBODY#N, MARVEL# (N), MIXED (N)
  $opaque = $name -match '^(GAMEBODY#|MARVEL#|MIXED|MARVEL# \(|MIXED \()'

  # Prefer a primary archive filename
  $archives = @(Get-ChildItem -LiteralPath $Dir.FullName -File -ErrorAction SilentlyContinue |
      Where-Object { $archiveExt -contains $_.Extension.ToLowerInvariant() } |
      Sort-Object Length -Descending)

  if ($archives.Count -eq 1 -or ($opaque -and $archives.Count -ge 1)) {
    $base = [IO.Path]::GetFileNameWithoutExtension($archives[0].Name)
    $base = $base -replace '\s*-\s*GAMBODY\s*$', '' -replace '\s*-\s*Gambody\s*$', '' -replace '\s*-\s*GAMBODY\s*', ' '
    return (Get-SafeName $base)
  }

  if ($archives.Count -gt 1 -and $opaque) {
    # Multiple archives: keep a cleaned dump name + first archive hint
    $hint = [IO.Path]::GetFileNameWithoutExtension($archives[0].Name)
    return (Get-SafeName ("$name - $hint"))
  }

  # If folder is already a decent name, keep it
  if (-not $opaque) {
    return (Get-SafeName $name)
  }

  return (Get-SafeName $name)
}

function Get-UniqueDestPath {
  param([string]$Category, [string]$ModelName)
  $destDir = Join-Path $DestRoot $Category
  $candidate = Join-Path $destDir $ModelName
  if (-not (Test-Path -LiteralPath $candidate)) { return $candidate }
  $i = 2
  while ($true) {
    $alt = Join-Path $destDir ("$ModelName ($i)")
    if (-not (Test-Path -LiteralPath $alt)) { return $alt }
    $i++
    if ($i -gt 500) { throw "Too many collisions for $ModelName in $Category" }
  }
}

function Move-ModelFolder {
  param(
    [string]$SourcePath,
    [string]$Category,
    [string]$ModelName,
    [string]$Reason
  )

  $ModelName = Get-SafeName $ModelName
  $dest = Get-UniqueDestPath -Category $Category -ModelName $ModelName
  $destName = Split-Path $dest -Leaf

  $action = if ($Apply) { 'MOVE' } else { 'DRY' }
  Write-Log "[$action] $SourcePath  ->  $Category\$destName  ($Reason)"

  $script:plan += [PSCustomObject]@{
    Action   = $action
    Source   = $SourcePath
    Category = $Category
    DestName = $destName
    Reason   = $Reason
  }

  if (-not $Apply) { return }

  $catPath = Join-Path $DestRoot $Category
  if (-not (Test-Path -LiteralPath $catPath)) {
    New-Item -ItemType Directory -Path $catPath -Force | Out-Null
  }

  # Rename in place first if needed, then move across share
  $parent = Split-Path $SourcePath -Parent
  $currentName = Split-Path $SourcePath -Leaf
  $working = $SourcePath

  if ($currentName -ne $destName) {
    $renamed = Join-Path $parent $destName
    # If rename target exists in source parent, use temp
    if (Test-Path -LiteralPath $renamed) {
      $renamed = Join-Path $parent ("__mf_tmp_{0}_{1}" -f $destName, [guid]::NewGuid().ToString('N').Substring(0, 8))
    }
    Rename-Item -LiteralPath $SourcePath -NewName (Split-Path $renamed -Leaf)
    $working = $renamed
  }

  Move-Item -LiteralPath $working -Destination $dest
}

function Wrap-LooseArchive {
  param([System.IO.FileInfo]$File, [string]$Category)

  $modelName = Get-SafeName ([IO.Path]::GetFileNameWithoutExtension($File.Name))
  $dest = Get-UniqueDestPath -Category $Category -ModelName $modelName
  $destName = Split-Path $dest -Leaf

  $action = if ($Apply) { 'WRAP' } else { 'DRY' }
  Write-Log "[$action] loose archive $($File.FullName)  ->  $Category\$destName\"

  $script:plan += [PSCustomObject]@{
    Action   = $action
    Source   = $File.FullName
    Category = $Category
    DestName = $destName
    Reason   = 'loose-archive'
  }

  if (-not $Apply) { return }

  $catPath = Join-Path $DestRoot $Category
  if (-not (Test-Path -LiteralPath $catPath)) {
    New-Item -ItemType Directory -Path $catPath -Force | Out-Null
  }
  New-Item -ItemType Directory -Path $dest -Force | Out-Null
  Move-Item -LiteralPath $File.FullName -Destination (Join-Path $dest $File.Name)
}

function Should-SkipDir {
  param([System.IO.DirectoryInfo]$Dir)
  $n = $Dir.Name
  if ($n.StartsWith('.')) { return $true }
  if ($n -like 'ALL *') { return $true }
  if ($n -eq 'New') { return $true }
  if ($n -match 'images?$') { return $true }
  return $false
}

function Process-ModelCandidates {
  param(
    [string]$BucketPath,
    [string]$Category
  )

  # Loose archives at bucket root
  Get-ChildItem -LiteralPath $BucketPath -File -ErrorAction SilentlyContinue | ForEach-Object {
    $ext = $_.Extension.ToLowerInvariant()
    if ($archiveExt -contains $ext) {
      Wrap-LooseArchive -File $_ -Category $Category
    }
    elseif ($modelExt -contains $ext) {
      # Loose mesh: wrap like archive
      Wrap-LooseArchive -File $_ -Category $Category
    }
    else {
      Write-Log "SKIP loose non-model file: $($_.FullName)" 'DEBUG'
    }
  }

  Get-ChildItem -LiteralPath $BucketPath -Directory -ErrorAction SilentlyContinue | ForEach-Object {
    if (Should-SkipDir $_) { Write-Log "SKIP dir: $($_.FullName)" 'DEBUG'; return }

    if ($SkipImagesOnly -and -not (Test-HasModelFiles $_.FullName)) {
      Write-Log "SKIP images-only: $($_.FullName)" 'WARN'
      $script:skippedImagesOnly++
      return
    }

    $modelName = Get-ModelNameFromFolder $_
    Move-ModelFolder -SourcePath $_.FullName -Category $Category -ModelName $modelName -Reason 'bucket-folder'
  }
}

function Resolve-AnyStlCategory {
  param([string]$SubfolderName)
  $n = $SubfolderName.ToLowerInvariant()
  foreach ($key in $anyStlMap.Keys) {
    if ($n -match [regex]::Escape($key)) { return $anyStlMap[$key] }
  }
  return 'Unknown'
}

function Process-AnyStl {
  $root = Join-Path $SourceRoot 'AnySTL'
  if (-not (Test-Path -LiteralPath $root)) { return }
  Get-ChildItem -LiteralPath $root -Directory -ErrorAction SilentlyContinue | ForEach-Object {
    if (Should-SkipDir $_) { return }
    $cat = Resolve-AnyStlCategory $_.Name
    Write-Log "AnySTL subfolder '$($_.Name)' -> category '$cat'"
    Process-ModelCandidates -BucketPath $_.FullName -Category $cat
  }
}

# --- main ---
if (-not (Test-Path -LiteralPath $SourceRoot)) { throw "Source not found: $SourceRoot" }
if (-not (Test-Path -LiteralPath $DestRoot)) { throw "Dest not found: $DestRoot" }

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$script:logFile = Join-Path $LogDir ("organize-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
$script:plan = [System.Collections.Generic.List[object]]::new()
$script:skippedImagesOnly = 0

Write-Log "Source: $SourceRoot"
Write-Log "Dest:   $DestRoot"
Write-Log "Mode:   $(if ($Apply) { 'APPLY (will move files)' } else { 'DRY-RUN (no changes)' })"

$toProcess = if ($Buckets.Count -gt 0) {
  $Buckets
}
else {
  @($bucketMap.Keys)
}

foreach ($bucket in $toProcess) {
  if ($bucket -eq 'AnySTL' -or $bucketMap[$bucket] -eq '_any_stl_expand') {
    Write-Log "=== Bucket: AnySTL (expand subcategories) ==="
    Process-AnyStl
    continue
  }

  $src = Join-Path $SourceRoot $bucket
  if (-not (Test-Path -LiteralPath $src)) {
    Write-Log "Bucket missing, skip: $bucket" 'WARN'
    continue
  }

  $cat = $bucketMap[$bucket]
  if (-not $cat) {
    Write-Log "No mapping for bucket '$bucket', using Unknown" 'WARN'
    $cat = 'Unknown'
  }

  Write-Log "=== Bucket: $bucket -> $cat ==="
  Process-ModelCandidates -BucketPath $src -Category $cat
}

# Summary
$csv = Join-Path $LogDir ("organize-plan-{0}.csv" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
$script:plan | Export-Csv -LiteralPath $csv -NoTypeInformation -Encoding UTF8

Write-Log "---- SUMMARY ----"
Write-Log ("Planned operations: {0}" -f $script:plan.Count)
Write-Log ("By category: {0}" -f (($script:plan | Group-Object Category | ForEach-Object { "$($_.Name)=$($_.Count)" }) -join ', '))
Write-Log ("Images-only skipped: {0}" -f $script:skippedImagesOnly)
Write-Log "Plan CSV: $csv"
Write-Log "Log file: $script:logFile"

if (-not $Apply) {
  Write-Host ""
  Write-Host "Dry-run complete. Re-run with -Apply to execute, optionally -Buckets to limit scope." -ForegroundColor Cyan
  Write-Host "Example: .\script\organize-unorg.ps1 -Buckets 'Dragon Ball Z','Star Wars','Gamebody' -Apply -SkipImagesOnly"
}
