<#
.SYNOPSIS
  Build a visual inventory of Unorg (and optionally Org) for Manyfold organization.

.DESCRIPTION
  Scans model folders, copies the best preview image into a local thumbs cache,
  and writes:
    <OutDir>\catalog.json   --" machine-readable inventory
    <OutDir>\index.html     --" browsable gallery (open in browser)
    <OutDir>\thumbs\        --" preview images for the gallery

  Manyfold library layout this targets:
    3D-Prints\<Category>\<Model Name>\  (files + optional preview.jpg)

.EXAMPLE
  # Full Unorg catalog (read-only scan)
  .\script\inventory-catalog.ps1

  # One bucket only (faster)
  .\script\inventory-catalog.ps1 -Buckets 'Dragon Ball Z','Star Wars','Gamebody'

  # Also index already-organized library
  .\script\inventory-catalog.ps1 -IncludeOrg

  # Then open gallery
  start \\192.168.11.102\Backups\3D-Prints-Unorg\.inventory\index.html
#>
[CmdletBinding()]
param(
  [string]$UnorgRoot = '\\192.168.11.102\Backups\3D-Prints-Unorg',
  [string]$OrgRoot = '\\192.168.11.102\Backups\3D-Prints',
  [string]$OutDir = '',
  [string[]]$Buckets = @(),
  [switch]$IncludeOrg,
  [switch]$SkipThumbs,
  [int]$MaxModels = 0
)

$ErrorActionPreference = 'Stop'

$imageExt = @('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp')
$archiveExt = @('.rar', '.zip', '.7z', '.cbz')
$modelExt = @('.stl', '.obj', '.3mf', '.ply', '.gltf', '.glb', '.step', '.stp', '.fbx', '.gcode', '.lys', '.lyt', '.chitubox', '.ctb', '.sl1s') + $archiveExt

# Same taxonomy as organize-unorg.ps1 / Manyfold library
$categories = @(
  'Anime', 'Cosplay', "D&D", 'DC', 'Games', 'Movie TV', 'Cartoons',
  'B3dserk', 'Cults3D', 'WICKED', 'AnySTL', 'Unknown'
)

$bucketMap = [ordered]@{
  'Alita Battle Angel'                         = 'Movie TV'
  'AnySTL'                                     = 'AnySTL'
  'Archive'                                    = 'Unknown'
  'Artisan Guild'                              = "D&D"
  'Busts Files'                                = 'Unknown'
  'Chibi'                                      = 'Anime'
  'Cults3D'                                    = 'Cults3D'
  "D&D"                                        = "D&D"
  'DC'                                         = 'DC'
  'Dragon Ball Z'                              = 'Anime'
  'etsy'                                       = 'Unknown'
  'Flexi'                                      = 'Unknown'
  'Gamebody'                                   = 'Games'
  'Halo'                                       = 'Games'
  'Harry Patter Chess Set'                     = 'Movie TV'
  'Helmet Mask'                                = 'Cosplay'
  'LOTR - keep - all'                          = 'Movie TV'
  'MartianSTLDESIGN'                           = 'Unknown'
  'Marvel Files'                               = 'Games'
  'MINIATURE FILES'                            = "D&D"
  'Mixed'                                      = 'Unknown'
  'MovieTv'                                    = 'Movie TV'
  'Pokemon'                                    = 'Anime'
  'RN Estudio'                                 = 'Unknown'
  'Sailor Moon'                                = 'Anime'
  'Silver Eyes Fredbear cosplay mask 3D model' = 'Cosplay'
  'Star Wars'                                  = 'Movie TV'
  'Thingiverse'                                = 'Unknown'
  'Tytan Troll'                                = "D&D"
  'Viking'                                     = 'Unknown'
  'Weapons'                                    = 'Cosplay'
  '_Uncategorized'                             = 'Unknown'
}

if (-not $OutDir) {
  $OutDir = Join-Path $UnorgRoot '.inventory'
}

$thumbsDir = Join-Path $OutDir 'thumbs'
New-Item -ItemType Directory -Path $thumbsDir -Force | Out-Null

function Write-Info([string]$msg) { Write-Host "[inventory] $msg" }

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

function Get-ThumbId([string]$path) {
  $bytes = [System.Text.Encoding]::UTF8.GetBytes($path.ToLowerInvariant())
  $sha = [System.Security.Cryptography.SHA1]::Create()
  try {
    ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') }) -join ''
  } finally { $sha.Dispose() }
}

function Find-BestPreview {
  param([string]$DirPath)

  if (-not (Test-Path -LiteralPath $DirPath)) { return $null }

  $preferNames = @(
    'preview.jpg', 'preview.jpeg', 'preview.png', 'preview.webp',
    'cover.jpg', 'cover.png', 'thumb.jpg', 'thumbnail.jpg', 'thumbnail.png'
  )

  foreach ($name in $preferNames) {
    $p = Join-Path $DirPath $name
    if (Test-Path -LiteralPath $p) { return $p }
  }

  # Root-level images (largest first --" often the product shot)
  $rootImgs = @(Get-ChildItem -LiteralPath $DirPath -File -ErrorAction SilentlyContinue |
      Where-Object { $imageExt -contains $_.Extension.ToLowerInvariant() -and $_.Name -notlike 'MIXED*' -and $_.Name -notlike 'MARVEL*' -and $_.Name -notlike 'GAMEBODY*' } |
      Sort-Object Length -Descending)
  if ($rootImgs.Count -gt 0) { return $rootImgs[0].FullName }

  # Any root image including dump codes
  $anyRoot = @(Get-ChildItem -LiteralPath $DirPath -File -ErrorAction SilentlyContinue |
      Where-Object { $imageExt -contains $_.Extension.ToLowerInvariant() } |
      Sort-Object Length -Descending)
  if ($anyRoot.Count -gt 0) { return $anyRoot[0].FullName }

  # images/ or Images/ subfolder
  foreach ($sub in @('images', 'Images', 'image', 'Image', 'pics', 'Pics')) {
    $imgDir = Join-Path $DirPath $sub
    if (-not (Test-Path -LiteralPath $imgDir)) { continue }
    $imgs = @(Get-ChildItem -LiteralPath $imgDir -File -ErrorAction SilentlyContinue |
        Where-Object { $imageExt -contains $_.Extension.ToLowerInvariant() } |
        Sort-Object Length -Descending)
    if ($imgs.Count -gt 0) { return $imgs[0].FullName }
  }

  # One level deep (common for multiparts)
  $subdirs = Get-ChildItem -LiteralPath $DirPath -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notlike '.*' -and $_.Name -notlike 'ALL *' } |
    Select-Object -First 8
  foreach ($d in $subdirs) {
    $imgs = @(Get-ChildItem -LiteralPath $d.FullName -File -ErrorAction SilentlyContinue |
        Where-Object { $imageExt -contains $_.Extension.ToLowerInvariant() } |
        Sort-Object Length -Descending |
        Select-Object -First 1)
    if ($imgs.Count -gt 0) { return $imgs[0].FullName }
  }

  return $null
}

function Get-ModelNameFromFolder {
  param([System.IO.DirectoryInfo]$Dir)

  $name = $Dir.Name
  $opaque = $name -match '^(GAMEBODY#|MARVEL#|MIXED|MARVEL# \(|MIXED \()'

  $archives = @(Get-ChildItem -LiteralPath $Dir.FullName -File -ErrorAction SilentlyContinue |
      Where-Object { $archiveExt -contains $_.Extension.ToLowerInvariant() } |
      Sort-Object Length -Descending)

  if ($archives.Count -ge 1 -and ($opaque -or $archives.Count -eq 1)) {
    $base = [IO.Path]::GetFileNameWithoutExtension($archives[0].Name)
    $base = $base -replace '\s*-\s*GAMBODY\s*$', '' -replace '\s*-\s*Gambody\s*$', ''
    return (Get-SafeName $base)
  }

  return (Get-SafeName $name)
}

function Test-IsModelFolder {
  param([string]$Path)
  $files = Get-ChildItem -LiteralPath $Path -File -ErrorAction SilentlyContinue
  foreach ($f in $files) {
    $ext = $f.Extension.ToLowerInvariant()
    if ($modelExt -contains $ext -or $imageExt -contains $ext) { return $true }
  }
  # One level deep: multiparts (Vegeta_body/foo.stl) or STL Files dumps
  $subs = Get-ChildItem -LiteralPath $Path -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notlike '.*' -and $_.Name -notlike 'ALL *' } |
    Select-Object -First 12
  foreach ($d in $subs) {
    $inner = Get-ChildItem -LiteralPath $d.FullName -File -ErrorAction SilentlyContinue |
      Select-Object -First 20
    foreach ($f in $inner) {
      $ext = $f.Extension.ToLowerInvariant()
      if ($modelExt -contains $ext -or $imageExt -contains $ext) { return $true }
    }
  }
  return $false
}

function Copy-Thumb {
  param([string]$SourceImage, [string]$ThumbId)
  if ($SkipThumbs -or -not $SourceImage) { return $null }
  $ext = [IO.Path]::GetExtension($SourceImage).ToLowerInvariant()
  if ($ext -notin $imageExt) { return $null }
  $destName = "$ThumbId$ext"
  $dest = Join-Path $thumbsDir $destName
  if (-not (Test-Path -LiteralPath $dest)) {
    try {
      Copy-Item -LiteralPath $SourceImage -Destination $dest -Force -ErrorAction Stop
    } catch {
      Write-Info "thumb copy failed: $SourceImage - $($_.Exception.Message)"
      return $null
    }
  }
  return "thumbs/$destName"
}

function New-CatalogEntry {
  param(
    [string]$SourcePath,
    [string]$DisplayName,
    [string]$Bucket,
    [string]$SuggestedCategory,
    [string]$Location, # unorg | org
    [string]$Kind      # folder | archive
  )

  $preview = $null
  if ($Kind -eq 'folder') {
    $preview = Find-BestPreview -DirPath $SourcePath
  } else {
    # Companion image next to archive: same basename
    $dir = Split-Path $SourcePath -Parent
    $base = [IO.Path]::GetFileNameWithoutExtension($SourcePath)
    foreach ($ext in $imageExt) {
      $cand = Join-Path $dir ($base + $ext)
      if (Test-Path -LiteralPath $cand) { $preview = $cand; break }
    }
  }

  $id = Get-ThumbId $SourcePath
  $thumbRel = if ($preview) { Copy-Thumb -SourceImage $preview -ThumbId $id } else { $null }

  [PSCustomObject]@{
    id                 = $id
    name               = $DisplayName
    sourcePath         = $SourcePath
    bucket             = $Bucket
    suggestedCategory  = $SuggestedCategory
    category           = $SuggestedCategory
    location           = $Location
    kind               = $Kind
    hasPreview         = [bool]$thumbRel
    previewSource      = $preview
    thumb              = $thumbRel
    status             = 'pending' # pending | keep | move | skip
  }
}

$entries = [System.Collections.Generic.List[object]]::new()

# --- Scan Unorg ---
Write-Info "Scanning Unorg: $UnorgRoot"
if (-not (Test-Path -LiteralPath $UnorgRoot)) { throw "Unorg root not found: $UnorgRoot" }

$bucketDirs = @(Get-ChildItem -LiteralPath $UnorgRoot -Directory -ErrorAction SilentlyContinue |
  Where-Object {
    $_.Name -notlike '.*' -and
    $_.Name -ne 'New' -and
    $_.Name -notlike '.manyfold*'
  })

# -File style: allow -Buckets "A,B,C" or multiple -Buckets values
$bucketFilter = @()
foreach ($b in $Buckets) {
  $bucketFilter += @($b -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}

if ($bucketFilter.Count -gt 0) {
  Write-Info "Filter buckets: $($bucketFilter -join ', ')"
  $bucketDirs = @($bucketDirs | Where-Object { $bucketFilter -contains $_.Name })
  Write-Info "Matched $($bucketDirs.Count) bucket folder(s)"
}

foreach ($bucket in $bucketDirs) {
  $suggested = if ($bucketMap.Contains($bucket.Name)) { $bucketMap[$bucket.Name] } else { 'Unknown' }
  Write-Info "  bucket: $($bucket.Name) -> $suggested"

  # AnySTL: one more level of subcategories
  if ($bucket.Name -eq 'AnySTL') {
    $subs = Get-ChildItem -LiteralPath $bucket.FullName -Directory -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -notlike '.*' -and $_.Name -notlike 'ALL *' }
    foreach ($sub in $subs) {
      $subSuggested = $suggested
      $ln = $sub.Name.ToLowerInvariant()
      if ($ln -match 'anime') { $subSuggested = 'Anime' }
      elseif ($ln -match 'cartoon') { $subSuggested = 'Cartoons' }
      elseif ($ln -match 'cosplay|helmet|weapon') { $subSuggested = 'Cosplay' }
      elseif ($ln -match 'dc') { $subSuggested = 'DC' }
      elseif ($ln -match 'game|marvel') { $subSuggested = 'Games' }
      elseif ($ln -match 'movie|tv') { $subSuggested = 'Movie TV' }
      elseif ($ln -match 'dnd|miniature|mini') { $subSuggested = "D&D" }
      elseif ($ln -match 'b3dserk') { $subSuggested = 'B3dserk' }

      Get-ChildItem -LiteralPath $sub.FullName -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notlike '.*' -and $_.Name -notlike 'ALL *' } |
        ForEach-Object {
          if (-not (Test-IsModelFolder $_.FullName)) { return }
          $entries.Add((New-CatalogEntry -SourcePath $_.FullName -DisplayName (Get-ModelNameFromFolder $_) `
              -Bucket "AnySTL/$($sub.Name)" -SuggestedCategory $subSuggested -Location 'unorg' -Kind 'folder'))
        }
    }
    continue
  }

  # Loose archives at bucket root (etsy, etc.)
  Get-ChildItem -LiteralPath $bucket.FullName -File -ErrorAction SilentlyContinue |
    Where-Object { $archiveExt -contains $_.Extension.ToLowerInvariant() } |
    ForEach-Object {
      $entries.Add((New-CatalogEntry -SourcePath $_.FullName `
          -DisplayName (Get-SafeName ([IO.Path]::GetFileNameWithoutExtension($_.Name))) `
          -Bucket $bucket.Name -SuggestedCategory $suggested -Location 'unorg' -Kind 'archive'))
    }

  # Model folders
  Get-ChildItem -LiteralPath $bucket.FullName -Directory -ErrorAction SilentlyContinue |
    Where-Object {
      $_.Name -notlike '.*' -and
      $_.Name -notlike 'ALL *' -and
      $_.Name -notmatch 'images?$'
    } |
    ForEach-Object {
      if (-not (Test-IsModelFolder $_.FullName)) { return }
      $entries.Add((New-CatalogEntry -SourcePath $_.FullName -DisplayName (Get-ModelNameFromFolder $_) `
          -Bucket $bucket.Name -SuggestedCategory $suggested -Location 'unorg' -Kind 'folder'))
    }

  if ($MaxModels -gt 0 -and $entries.Count -ge $MaxModels) { break }
}

# --- Optional Org scan (inventory only, already organized) ---
if ($IncludeOrg -and (Test-Path -LiteralPath $OrgRoot)) {
  Write-Info "Scanning Org: $OrgRoot"
  Get-ChildItem -LiteralPath $OrgRoot -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notlike '.*' } |
    ForEach-Object {
      $cat = $_.Name
      Get-ChildItem -LiteralPath $_.FullName -Directory -ErrorAction SilentlyContinue |
        ForEach-Object {
          $entries.Add((New-CatalogEntry -SourcePath $_.FullName -DisplayName (Get-SafeName $_.Name) `
              -Bucket $cat -SuggestedCategory $cat -Location 'org' -Kind 'folder'))
        }
    }
}

if ($MaxModels -gt 0 -and $entries.Count -gt $MaxModels) {
  $entries = [System.Collections.Generic.List[object]]::new($entries.GetRange(0, $MaxModels))
}

Write-Info "Catalogued $($entries.Count) items ($((@($entries | Where-Object hasPreview)).Count) with previews)"

# --- Write catalog.json ---
$catalogPath = Join-Path $OutDir 'catalog.json'
$payload = [ordered]@{
  generatedAt = (Get-Date).ToString('o')
  unorgRoot   = $UnorgRoot
  orgRoot     = $OrgRoot
  categories  = $categories
  count       = $entries.Count
  withPreview = (@($entries | Where-Object hasPreview)).Count
  items       = @($entries)
}
$payload | ConvertTo-Json -Depth 6 -Compress:$false | Set-Content -LiteralPath $catalogPath -Encoding UTF8
Write-Info "Wrote $catalogPath"

# --- Write index.html gallery (template lives beside this script) ---
$categoriesJson = ($categories | ConvertTo-Json -Compress)
$itemsJson = ($entries | ConvertTo-Json -Depth 5 -Compress)
$templatePath = Join-Path $PSScriptRoot 'inventory-gallery.template.html'
if (-not (Test-Path -LiteralPath $templatePath)) { throw "Missing template: $templatePath" }
$html = Get-Content -LiteralPath $templatePath -Raw -Encoding UTF8
$html = $html.Replace('__ITEMS_JSON__', $itemsJson).Replace('__CATEGORIES_JSON__', $categoriesJson)
$htmlPath = Join-Path $OutDir 'index.html'
Set-Content -LiteralPath $htmlPath -Value $html -Encoding UTF8
Write-Info "Wrote $htmlPath"

# Summary
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Inventory ready"
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Items:    $($entries.Count)"
Write-Host " Previews: $((@($entries | Where-Object hasPreview)).Count)"
Write-Host " Output:   $OutDir"
Write-Host ""
Write-Host "Open gallery:"
Write-Host "  start `"$htmlPath`""
Write-Host ""
Write-Host "Workflow:"
Write-Host "  1. Browse thumbs, set category, mark Move/Skip"
Write-Host "  2. Export decisions.json"
Write-Host "  3. Apply with:"
Write-Host "       .\script\organize-from-decisions.ps1 -DecisionsPath .\decisions.json -Apply"
Write-Host ""

