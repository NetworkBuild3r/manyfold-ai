<#
.SYNOPSIS
  Extract preview images from .zip archives in 3D-Prints-Unorg (and optionally organized library).

.DESCRIPTION
  Manyfold (and the inventory gallery) only see images that exist as files on disk.
  Product shots often live *inside* .zip dumps. This script opens each zip, finds
  image entries, and writes them next to the model so Manyfold can use them as
  previews after a rescan.

  For each zip:
    - All qualifying images  ->  <modelDir>\images\  (from zip)
    - Best candidate also    ->  <modelDir>\preview.<ext>  (if no preview already)

  "Model dir" is:
    - The zip's parent folder when the zip sits inside a model folder, OR
    - A folder named after the zip (basename) when the zip is loose next to peers.

  Safe defaults: -WhatIf (dry-run), skip if preview.jpg already exists, skip tiny
  icons, path-traversal hardened.

.EXAMPLE
  # Dry-run one bucket
  .\script\extract-zip-previews.ps1 -Buckets 'etsy','Dragon Ball Z' -WhatIf

.EXAMPLE
  # Apply on Unorg
  .\script\extract-zip-previews.ps1 -Buckets 'etsy' -Apply

.EXAMPLE
  # Full Unorg (slow on NAS)
  .\script\extract-zip-previews.ps1 -Apply

.EXAMPLE
  # Also process organized 3D-Prints
  .\script\extract-zip-previews.ps1 -AlsoOrganized -Apply
#>
[CmdletBinding()]
param(
  [string]$UnorgRoot = '\\192.168.11.102\Backups\3D-Prints-Unorg',
  [string]$OrgRoot = '\\192.168.11.102\Backups\3D-Prints',
  [string[]]$Buckets = @(),
  # Optional: one zip file, or a folder to scan (overrides Unorg/Buckets when set)
  [string]$Path = '',
  [switch]$AlsoOrganized,
  [switch]$Apply,
  # Extract every image into images/ (default). If off, only writes preview.*
  [switch]$AllImages,
  [int]$MaxImagesPerZip = 30,
  [int]$MinImageBytes = 8KB,
  [int]$MaxDepth = 8,
  [string]$LogDir = ''
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$imageExt = @('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp')
$preferNameHints = @(
  'preview', 'cover', 'thumb', 'thumbnail', 'product', 'render', 'main',
  'photo', 'front', 'hero', 'display', 'poster', 'image'
)
$skipNameHints = @('icon', 'logo', 'favicon', 'sprite', 'button', 'badge', 'emoji')

if (-not $PSBoundParameters.ContainsKey('AllImages')) {
  # Default: extract all images into images/ plus best as preview
  $AllImages = $true
}

if (-not $LogDir) {
  $LogDir = Join-Path $UnorgRoot '.manyfold-organize-logs'
}

function Write-Info([string]$msg) { Write-Host $msg }
function Write-Warn2([string]$msg) { Write-Host "WARN: $msg" -ForegroundColor Yellow }

function Test-IsImageEntry {
  param([string]$Name)
  $ext = [IO.Path]::GetExtension($Name).ToLowerInvariant()
  return $imageExt -contains $ext
}

function Get-SafeRelativePath {
  param([string]$EntryName)
  # Zip entries use / ; normalize and block traversal
  $n = $EntryName -replace '\\', '/'
  $n = $n.TrimStart('/')
  if ($n -match '(^|/)\.\.(/|$)') { return $null }
  if ($n -match '^[A-Za-z]:') { return $null }
  return $n
}

function Get-ImageScore {
  param(
    [string]$EntryName,
    [long]$Length
  )
  $base = [IO.Path]::GetFileNameWithoutExtension($EntryName).ToLowerInvariant()
  $score = [Math]::Min([double]$Length, 50MB)  # size helps pick product shots

  foreach ($h in $preferNameHints) {
    if ($base -eq $h -or $base.StartsWith($h) -or $base.Contains($h)) {
      $score += 50MB
      break
    }
  }
  foreach ($h in $skipNameHints) {
    if ($base.Contains($h)) {
      $score -= 20MB
      break
    }
  }
  # Prefer shallow paths (not buried 8 levels deep)
  $depth = ($EntryName -split '[/\\]').Count
  $score -= ($depth * 100KB)
  # Prefer root-ish names over long junk
  if ($base.Length -lt 40) { $score += 1MB }
  return $score
}

function Get-ModelDirForZip {
  param([System.IO.FileInfo]$ZipFile)

  $parent = $ZipFile.Directory
  if (-not $parent) { return $null }

  $base = [IO.Path]::GetFileNameWithoutExtension($ZipFile.Name)
  $baseSafe = $base -replace '[<>:"/\\|?*\x00-\x1F]', ' '
  $baseSafe = ($baseSafe -replace '\s+', ' ').Trim(' .')
  if ([string]::IsNullOrWhiteSpace($baseSafe)) { $baseSafe = 'unnamed-model' }
  if ($baseSafe.Length -gt 120) { $baseSafe = $baseSafe.Substring(0, 120).Trim() }

  $namedFolder = Join-Path $parent.FullName $baseSafe

  # Already inside a folder named for this model
  if ($parent.Name -eq $baseSafe) {
    return $parent.FullName
  }

  # Prefer existing sibling folder matching the zip basename
  if (Test-Path -LiteralPath $namedFolder) {
    return $namedFolder
  }

  $siblingZips = @(Get-ChildItem -LiteralPath $parent.FullName -File -Filter '*.zip' -ErrorAction SilentlyContinue)
  $siblingDirs = @(Get-ChildItem -LiteralPath $parent.FullName -Directory -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -notlike '.*' -and $_.Name -ne 'images' -and $_.Name -ne 'Images' })
  $siblingFiles = @(Get-ChildItem -LiteralPath $parent.FullName -File -ErrorAction SilentlyContinue |
      Where-Object { $_.Extension -notin @('.zip', '.rar', '.7z') })

  # Loose zip sitting in a category/bucket that already has other model folders or many zips
  # → create/use <parent>\<zipBasename>\ so we never dump previews into the category root
  if ($siblingDirs.Count -ge 2 -or $siblingZips.Count -ge 2) {
    return $namedFolder
  }

  # Parent is a dedicated model folder (zip + maybe stl/images only)
  if ($siblingFiles.Count -gt 0 -or $siblingDirs.Count -le 1) {
    return $parent.FullName
  }

  return $namedFolder
}

function Get-ZipImageEntries {
  param([string]$ZipPath)

  $results = New-Object System.Collections.Generic.List[object]
  $zip = $null
  try {
    $zip = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
    foreach ($entry in $zip.Entries) {
      if ($entry.Length -le 0) { continue }
      if ($entry.FullName.EndsWith('/')) { continue }
      $rel = Get-SafeRelativePath $entry.FullName
      if (-not $rel) { continue }
      if (-not (Test-IsImageEntry $rel)) { continue }
      if ($entry.Length -lt $MinImageBytes) { continue }

      $fileName = [IO.Path]::GetFileName($rel)
      $base = [IO.Path]::GetFileNameWithoutExtension($fileName).ToLowerInvariant()
      $skip = $false
      foreach ($h in $skipNameHints) {
        if ($base -eq $h) { $skip = $true; break }
      }
      if ($skip) { continue }

      $score = Get-ImageScore -EntryName $rel -Length $entry.Length
      $results.Add([pscustomobject]@{
          EntryName = $entry.FullName
          RelPath   = $rel
          FileName  = $fileName
          Length    = [long]$entry.Length
          Score     = $score
        }) | Out-Null
    }
  } catch {
    Write-Warn2 "Cannot open zip: $ZipPath - $($_.Exception.Message)"
    return @()
  } finally {
    if ($zip) { $zip.Dispose() }
  }

  return @($results | Sort-Object Score -Descending)
}

function Expand-ZipImageEntry {
  param(
    [string]$ZipPath,
    [string]$EntryName,
    [string]$DestPath
  )

  $dir = Split-Path -Parent $DestPath
  if (-not (Test-Path -LiteralPath $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
  }

  $zip = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
  try {
    $entry = $zip.GetEntry($EntryName)
    if (-not $entry) {
      # Some zips use different separators
      $entry = $zip.Entries | Where-Object { $_.FullName -eq $EntryName -or ($_.FullName -replace '\\', '/') -eq ($EntryName -replace '\\', '/') } | Select-Object -First 1
    }
    if (-not $entry) { throw "Entry not found: $EntryName" }

    $destStream = [System.IO.File]::Open($DestPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write)
    try {
      $src = $entry.Open()
      try {
        $src.CopyTo($destStream)
      } finally { $src.Dispose() }
    } finally { $destStream.Dispose() }
  } finally {
    $zip.Dispose()
  }
}

function Test-HasPreview {
  param([string]$ModelDir)
  foreach ($name in @('preview.jpg', 'preview.jpeg', 'preview.png', 'preview.webp', 'cover.jpg', 'cover.png', 'thumb.jpg', 'thumbnail.jpg')) {
    if (Test-Path -LiteralPath (Join-Path $ModelDir $name)) { return $true }
  }
  return $false
}

function Process-Zip {
  param([System.IO.FileInfo]$ZipFile)

  $modelDir = Get-ModelDirForZip -ZipFile $ZipFile
  if (-not $modelDir) {
    return [pscustomobject]@{ Zip = $ZipFile.FullName; Status = 'skip-no-modeldir'; Images = 0; Preview = $null }
  }

  $images = @(Get-ZipImageEntries -ZipPath $ZipFile.FullName)
  if ($images.Count -eq 0) {
    return [pscustomobject]@{ Zip = $ZipFile.FullName; Status = 'no-images'; Images = 0; Preview = $null; ModelDir = $modelDir }
  }

  $toExtract = @($images | Select-Object -First $MaxImagesPerZip)
  $best = $toExtract[0]
  $extracted = 0
  $previewPath = $null
  $actions = New-Object System.Collections.Generic.List[string]

  # Ensure model dir exists (for loose zips that need a folder)
  if ($Apply -and -not (Test-Path -LiteralPath $modelDir)) {
    New-Item -ItemType Directory -Path $modelDir -Force | Out-Null
    $actions.Add("mkdir $modelDir")
  }

  $imagesDir = Join-Path $modelDir 'images'
  $hasPreview = Test-HasPreview -ModelDir $modelDir

  if ($AllImages) {
    foreach ($img in $toExtract) {
      # Flatten to images/<filename>; skip if already extracted
      $destName = $img.FileName
      $dest = Join-Path $imagesDir $destName
      if (Test-Path -LiteralPath $dest) { continue }

      if ($Apply) {
        try {
          Expand-ZipImageEntry -ZipPath $ZipFile.FullName -EntryName $img.EntryName -DestPath $dest
          $extracted++
          $actions.Add("extract images/$destName ($([math]::Round($img.Length/1KB))KB)")
        } catch {
          Write-Warn2 "extract failed $($img.EntryName): $($_.Exception.Message)"
        }
      } else {
        $extracted++
        $actions.Add("WOULD extract images/$destName ($([math]::Round($img.Length/1KB))KB score=$([math]::Round($img.Score/1MB,1))MB)")
      }
    }
  }

  # Best image as preview.* at model root (Manyfold-friendly)
  if (-not $hasPreview) {
    $ext = [IO.Path]::GetExtension($best.FileName).ToLowerInvariant()
    if ($ext -eq '.jpeg') { $ext = '.jpg' }
    $previewPath = Join-Path $modelDir ("preview$ext")
    if (-not (Test-Path -LiteralPath $previewPath)) {
      if ($Apply) {
        try {
          Expand-ZipImageEntry -ZipPath $ZipFile.FullName -EntryName $best.EntryName -DestPath $previewPath
          $actions.Add("preview$ext from $($best.RelPath)")
        } catch {
          Write-Warn2 "preview extract failed: $($_.Exception.Message)"
          $previewPath = $null
        }
      } else {
        $actions.Add("WOULD write preview$ext from $($best.RelPath) ($([math]::Round($best.Length/1KB))KB)")
      }
    }
  } else {
    $actions.Add('preview already present — skipped')
  }

  return [pscustomobject]@{
    Zip      = $ZipFile.FullName
    ModelDir = $modelDir
    Status   = if ($Apply) { 'applied' } else { 'dry-run' }
    Images   = $extracted
    Preview  = $previewPath
    Best     = $best.RelPath
    Actions  = ($actions -join '; ')
  }
}

function Get-ZipsUnder {
  param([string]$Root, [string[]]$OnlyBuckets)

  if (-not (Test-Path -LiteralPath $Root)) {
    Write-Warn2 "Root not found: $Root"
    return @()
  }

  $searchRoots = @()
  if ($OnlyBuckets -and $OnlyBuckets.Count -gt 0) {
    foreach ($b in $OnlyBuckets) {
      $p = Join-Path $Root $b
      if (Test-Path -LiteralPath $p) { $searchRoots += $p }
      else { Write-Warn2 "Bucket not found: $p" }
    }
  } else {
    $searchRoots = @($Root)
  }

  $all = New-Object System.Collections.Generic.List[System.IO.FileInfo]
  foreach ($sr in $searchRoots) {
    Write-Info "Scanning zips under: $sr (max depth $MaxDepth)"
    # Depth-limited walk to avoid huge Archive trees hanging forever
    $queue = [System.Collections.Generic.Queue[object]]::new()
    $queue.Enqueue([pscustomobject]@{ Path = $sr; Depth = 0 })
    while ($queue.Count -gt 0) {
      $cur = $queue.Dequeue()
      if ($cur.Depth -gt $MaxDepth) { continue }
      $name = Split-Path $cur.Path -Leaf
      if ($name -like '.*') { continue }
      if ($name -eq '#recycle' -or $name -eq '@eaDir') { continue }

      try {
        Get-ChildItem -LiteralPath $cur.Path -File -Filter '*.zip' -ErrorAction SilentlyContinue |
          ForEach-Object { $all.Add($_) }
      } catch {}

      if ($cur.Depth -lt $MaxDepth) {
        try {
          Get-ChildItem -LiteralPath $cur.Path -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -notlike '.*' -and $_.Name -ne '#recycle' -and $_.Name -ne '@eaDir' } |
            ForEach-Object { $queue.Enqueue([pscustomobject]@{ Path = $_.FullName; Depth = $cur.Depth + 1 }) }
        } catch {}
      }
    }
  }
  return @($all)
}

# --- main ---
$mode = if ($Apply) { 'APPLY' } else { 'DRY-RUN (pass -Apply to write files)' }
Write-Info "=== extract-zip-previews ($mode) ==="
Write-Info "Unorg: $UnorgRoot"
if ($AlsoOrganized) { Write-Info "Org:   $OrgRoot" }
if ($Buckets.Count -gt 0) { Write-Info "Buckets: $($Buckets -join ', ')" }

$zips = @()
if ($Path) {
  if (-not (Test-Path -LiteralPath $Path)) {
    throw "Path not found: $Path"
  }
  $item = Get-Item -LiteralPath $Path
  if ($item.PSIsContainer) {
    Write-Info "Scanning path: $Path"
    $zips = @(Get-ZipsUnder -Root $Path -OnlyBuckets @())
  } elseif ($item.Extension -eq '.zip') {
    $zips = @($item)
  } else {
    throw "Path must be a .zip or a directory: $Path"
  }
} else {
  $zips = @(Get-ZipsUnder -Root $UnorgRoot -OnlyBuckets $Buckets)
  if ($AlsoOrganized) {
    $zips += @(Get-ZipsUnder -Root $OrgRoot -OnlyBuckets @())
  }
}

Write-Info "Found $($zips.Count) zip file(s)"

$results = New-Object System.Collections.Generic.List[object]
$i = 0
foreach ($z in $zips) {
  $i++
  if (($i % 25) -eq 0 -or $i -eq 1) {
    Write-Info "[$i/$($zips.Count)] $($z.FullName)"
  }
  try {
    $r = Process-Zip -ZipFile $z
    $results.Add($r) | Out-Null
  } catch {
    Write-Warn2 "Failed $($z.FullName): $($_.Exception.Message)"
    $results.Add([pscustomobject]@{
        Zip = $z.FullName; Status = 'error'; Images = 0; Preview = $null; Actions = $_.Exception.Message
      }) | Out-Null
  }
}

$withImages = @($results | Where-Object { $_.Images -gt 0 -or $_.Preview })
$noImages = @($results | Where-Object { $_.Status -eq 'no-images' })
$errors = @($results | Where-Object { $_.Status -eq 'error' })

Write-Info ""
Write-Info "=== Summary ==="
Write-Info "Zips scanned:     $($results.Count)"
Write-Info "With images:      $($withImages.Count)"
Write-Info "No images in zip: $($noImages.Count)"
Write-Info "Errors:           $($errors.Count)"
if (-not $Apply) {
  Write-Info "Dry-run only. Re-run with -Apply to extract."
}

# Log
if (-not (Test-Path -LiteralPath $LogDir)) {
  try { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null } catch {}
}
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$logPath = Join-Path $LogDir "extract-zip-previews-$stamp.json"
try {
  $results | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $logPath -Encoding UTF8
  Write-Info "Log: $logPath"
} catch {
  Write-Warn2 "Could not write log: $($_.Exception.Message)"
}

# Sample
Write-Info ""
Write-Info "Sample (up to 15 with images):"
$withImages | Select-Object -First 15 | ForEach-Object {
  Write-Info ("  [{0}] {1}" -f $_.Status, $_.Zip)
  if ($_.Best) { Write-Info ("       best: {0}" -f $_.Best) }
  if ($_.Actions) { Write-Info ("       {0}" -f $_.Actions) }
}

Write-Info ""
Write-Info "After -Apply: rescan the library in Manyfold (or re-run inventory-catalog.ps1) so previews show up."
